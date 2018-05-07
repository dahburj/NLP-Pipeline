import numpy as np
import spacy
from spacy.attrs import LOWER, LIKE_URL, LIKE_EMAIL, ORTH, IS_PUNCT, LEMMA, IS_OOV
from spacy.pipeline import Tagger, DependencyParser, EntityRecognizer
import gensim
from gensim.models.doc2vec import TaggedDocument
from gensim.models import Doc2Vec
import tensorflow as tf
import os

import sys

'''
TODO - 

1) Make nlp object init make more sense - IMPORTANT
2) Add assert statements for assuring parameters are correct
3) Add sentence t
4) Add multiple contexts to tfrecords writer function
5) Add inferred compression type based off of file name in tfrecords writer function
'''
class SpacyProcessor:

    def __init__(self, textfile, max_length, tokenize_sentences = False, num_sentences = 4, gn_path=None, use_google_news=False,
                nlp=None, nlp_object_path = None, vectors=None, skip="<SKIP>", merge=False, num_threads=8, delete_punctuation=False,
                token_type="lower", skip_oov=False, save_tokenized_text_data=False, bad_deps=("amod", "compound")):
        



        """Summary
        
        Args:
            textfile (str): Path to the line delimited text file
            max_length (int): Length to limit/pad sequences to
            tokenize_sentences (bool, optional): Description
            num_sentences (int, optional): Description
            gn_path (str): Path to google news vectors bin file if nlp object has not been saved yet
            use_google_news (bool, optional): If True, we will use google news vectors stored at gn_path (or elsewhere)
            nlp (None, optional): Pre-initialized Spacy NLP object 
            nlp_object_path (None, optional): When passed, it will load the nlp object found in this path
            skip (str, optional): Short documents will be padded with this variable up until max_length
            merge (bool, optional): When True, we will merge noun phrases and named entities into single tokens
            num_threads (int, optional): Number of threads to parallelize the pipeline
            delete_punctuation (bool, optional): When set to true, punctuation will be deleted when tokenizing
            token_type (str, optional): String denoting type of token for tokenization. Options are "lower", "lemma", and "orth"
            skip_oov (bool, optional): When set to true, it will replace out of vocabulary words with skip token. 
                                       Note: Setting this to false when planning to initialize random vectors will allow for learning
                                       the out of vocabulary words/phrases.
            save_tokenized_text_data (bool, optional): Description
            bad_deps (tuple, optional): Description
        """



        self.gn_path = gn_path
        self.textfile = textfile
        self.max_length = max_length
        self.skip = skip
        self.nlp = nlp
        self.merge = merge
        self.num_threads = num_threads
        self.delete_punctuation = delete_punctuation
        self.token_type = token_type
        self.skip_oov = skip_oov
        self.save_tokenized_text_data = save_tokenized_text_data
        self.bad_deps = bad_deps
        self.tokenize_sentences = tokenize_sentences
        self.num_sentences = num_sentences
        self.nlp_object_path = nlp_object_path
        self.vectors = vectors

        # If a spacy nlp object is not passed to init
        if self.nlp==None:
            # Load nlp object from path provided
            if nlp_object_path:
                self.nlp=spacy.load(self.nlp_object_path)
            # Load google news from binary file 
            elif self.gn_path:
                self.load_google_news()
            # Use vectors path from saved dist-packages location
            elif self.vectors:
                self.nlp = spacy.load('en_core_web_lg', vectors=self.vectors)
            # If nothing is specified, load spacy model
            else:
                self.nlp = spacy.load('en_core_web_lg')

        self.tokenize()

    def load_google_news(self):
        '''
        to get frequencies
        vocab_obj = model.vocab["word"]
        vocab_obj.count
        '''

        # Load google news vecs in gensim
        self.model = gensim.models.KeyedVectors.load_word2vec_format(self.gn_path, binary=True)

        # Init blank english spacy nlp object
        self.nlp = spacy.load('en_core_web_lg', vectors=False)

        # Loop through range of all indexes, get words associated with each index.
        # The words in the keys list will correspond to the order of the google embed matrix
        self.keys = []
        for idx in range(3000000):
            word = self.model.index2word[idx]
            word = word.lower()
            self.keys.append(word)
            # Add the word to the nlp vocab
            self.nlp.vocab.strings.add(word)

        # Set the vectors for our nlp object to the google news vectors
        self.nlp.vocab.vectors = spacy.vocab.Vectors(data=self.model.syn0, keys=self.keys)


    def tokenize(self):
        # Read in text data from textfile path
        self.texts = open(self.textfile).read().split('\n')

        # Get number of documents supplied
        self.num_docs = len(self.texts)
        
        # Init data as a bunch of zeros - shape [num_texts, max_length]
        self.data = np.zeros((len(self.texts), self.max_length), dtype=np.uint64)
        
        # Add the skip token to the vocab, creating a unique hash for it
        self.nlp.vocab.strings.add(self.skip)
        self.skip = self.nlp.vocab.strings[self.skip]
        self.data[:] = self.skip

        # Make array to store row numbers of documents that must be deleted
        self.purged_docs = []

        # This array will hold tokenized text data if it is asked for
        if self.save_tokenized_text_data:
            self.text_data = []

        if self.tokenize_sentences:
            self.sentence_tokenize()
            return
        for row, doc in enumerate(self.nlp.pipe(self.texts, n_threads=self.num_threads, batch_size=10000)):
            try:
                if self.merge:
                    # Make list to hold merged phrases. Necessary to avoid buggy spacy merge implementation
                    phrase_list = []
                    # Merge noun phrases into single tokens
                    for phrase in list(doc.noun_chunks):
                        while len(phrase) > 1 and phrase[0].dep_ not in self.bad_deps:
                            phrase = phrase[1:]
                        if len(phrase) > 1:
                            phrase_list.append(phrase)
                    
                    # Merge phrases onto doc using doc.merge. Phrase.merge breaks.
                    if len(phrase_list) > 0:
                        for _phrase in phrase_list:
                            doc.merge(start_idx=_phrase[0].idx,
                                      end_idx=_phrase[len(_phrase) - 1].idx + len(_phrase[len(_phrase) - 1]),
                                      tag=_phrase[0].tag_,
                                      lemma='_'.join([token.text for token in _phrase]),
                                      ent_type=_phrase[0].ent_type_)
                    ent_list = []
                    # Iterate over named entities
                    for ent in doc.ents:
                        if len(ent) > 1:
                            ent_list.append(ent)
                    
                    # Merge entities onto doc using doc.merge. ent.merge breaks.
                    if len(ent_list) > 0:
                        for _ent in ent_list:
                            doc.merge(start_idx=_ent[0].idx,
                                      end_idx=_ent[len(_ent) - 1].idx + len(_ent[len(_ent) - 1]),
                                      tag=_ent.root.tag_,
                                      lemma='_'.join([token.text for token in _ent]),
                                      ent_type=_ent[0].ent_type_)

                # Create temp list for holding doc text
                if self.save_tokenized_text_data:
                    doc_text = []

                # Loop through tokens in doc
                for token in doc:
                    # Replaces spaces between phrases with underscore
                    text = token.text.replace(" ", "_")
                    # Get the string token for the given token type
                    if self.token_type=="lower":
                        _token = token.lower_
                    elif self.token_type=="lemma":
                        _token = token.lemma_
                    else:
                        _token = token.orth_

                    # Add token to spacy string list so we can use oov as known hash tokens
                    if token.is_oov:
                        self.nlp.vocab.strings.add(_token)

                    if self.save_tokenized_text_data:
                        doc_text.append(_token)

                if self.save_tokenized_text_data:
                    self.text_data.append(doc_text)

                # Options for how to tokenize
                if self.token_type=="lower":
                    dat = doc.to_array([LOWER, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])
                elif self.token_type=="lemma":
                    dat = doc.to_array([LEMMA, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])
                else:
                    dat = doc.to_array([ORTH, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])

                if len(dat) > 0:
                    msg = "Negative indices reserved for special tokens"
                    assert dat.min() >= 0, msg
                    if self.skip_oov:
                        # Get Indexes of email and URL and oov tokens
                        idx = (dat[:, 1] > 0) | (dat[:, 2] > 0) | (dat[:, 3] > 0)
                    else:
                        # Get Indexes of email and URL tokens
                        idx = (dat[:, 1] > 0) | (dat[:, 2] > 0)                    
                    # Replace email and URL tokens with skip token
                    dat[idx] = self.skip
                    # Delete punctuation
                    if self.delete_punctuation:
                        delete = np.where(dat[:,3]==1)
                        dat = np.delete(dat, delete, 0)
                    length = min(len(dat), self.max_length)
                    self.data[row, :length] = dat[:length, 0].ravel()
            except Exception as e:
                print("Warning! Document", row, "broke, likely due to spaCy merge issues.\nMore info at thier github, issues #1547 and #1474")
                self.purged_docs.append(row)
                continue

        # If necessary, delete documents that failed to tokenize correctly.
        self.data = np.delete(self.data, self.purged_docs, 0).astype(np.uint64)
        # Unique tokens
        self.uniques = np.unique(self.data)
        # Saved Spacy Vocab
        self.vocab = self.nlp.vocab
        # Making an idx to word mapping for vocab
        self.hash_to_word = {}
        # Manually putting in this hash for the padding ID
        self.hash_to_word[self.skip] = '<SKIP>'
        # If lemma, manually put in hash for the pronoun ID
        if self.token_type=="lemma":
            self.hash_to_word[self.nlp.vocab.strings["-PRON-"]] = "-PRON-"
        
        for v in self.uniques:
            if v!= self.skip:
                try:
                    if self.token_type == "lower":
                        self.hash_to_word[v] = self.nlp.vocab[v].lower_
                    elif self.token_type == "lemma":
                        self.hash_to_word[v] = self.nlp.vocab[v].lemma_
                    else:
                        self.hash_to_word[v] = self.nlp.vocab[v].orth_
                except:
                    pass

    def sentence_tokenize(self,):        
        # Data will have shape [Num Docs, None, Seq_Len]
        self.data = np.zeros([self.num_docs, self.num_sentences, self.max_length], dtype=np.uint64)
        self.data[:] = self.skip

        for row, full_doc in enumerate(self.nlp.pipe(self.texts, n_threads=self.num_threads, batch_size=10000)):

            # Split doc into sentences
            sentences = [sent for sent in full_doc.sents]

            # For SENTENCE in sentences
            for sent_idx, doc in enumerate(sentences):
                # We don't want to process more than num sentences for each doc.
                # We limit the number of sentences tokenized to num_sentences
                if sent_idx >= self.num_sentences:
                    continue
                try:
                    if self.merge:
                        # Make list to hold merged phrases. Necessary to avoid buggy spacy merge implementation
                        phrase_list = []
                        # Merge noun phrases into single tokens
                        for phrase in list(doc.noun_chunks):
                            while len(phrase) > 1 and phrase[0].dep_ not in self.bad_deps:
                                phrase = phrase[1:]
                            if len(phrase) > 1:
                                phrase_list.append(phrase)
                        
                        # Merge phrases onto doc using doc.merge. Phrase.merge breaks.
                        if len(phrase_list) > 0:
                            for _phrase in phrase_list:
                                doc.merge(start_idx=_phrase[0].idx,
                                          end_idx=_phrase[len(_phrase) - 1].idx + len(_phrase[len(_phrase) - 1]),
                                          tag=_phrase[0].tag_,
                                          lemma='_'.join([token.text for token in _phrase]),
                                          ent_type=_phrase[0].ent_type_)
                        ent_list = []
                        # Iterate over named entities
                        for ent in doc.ents:
                            if len(ent) > 1:
                                ent_list.append(ent)
                        
                        # Merge entities onto doc using doc.merge. ent.merge breaks.
                        if len(ent_list) > 0:
                            for _ent in ent_list:
                                doc.merge(start_idx=_ent[0].idx,
                                          end_idx=_ent[len(_ent) - 1].idx + len(_ent[len(_ent) - 1]),
                                          tag=_ent.root.tag_,
                                          lemma='_'.join([token.text for token in _ent]),
                                          ent_type=_ent[0].ent_type_)
                    # Create temp list for holding doc text
                    if self.save_tokenized_text_data:
                        doc_text = []

                    # Loop through tokens in doc
                    for token in doc:
                        # Replaces spaces between phrases with underscore
                        text = token.text.replace(" ", "_")
                        # Get the string token for the given token type
                        if self.token_type=="lower":
                            _token = token.lower_
                        elif self.token_type=="lemma":
                            _token = token.lemma_
                        else:
                            _token = token.orth_

                        # Add token to spacy string list so we can use oov as known hash tokens
                        if token.is_oov:
                            self.nlp.vocab.strings.add(_token)

                        if self.save_tokenized_text_data:
                            doc_text.append(_token)

                    if self.save_tokenized_text_data:
                        self.text_data.append(doc_text)

                    # Options for how to tokenize
                    if self.token_type=="lower":
                        dat = doc.to_array([LOWER, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])
                    elif self.token_type=="lemma":
                        dat = doc.to_array([LEMMA, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])
                    else:
                        dat = doc.to_array([ORTH, LIKE_EMAIL, LIKE_URL, IS_OOV, IS_PUNCT])

                    if len(dat) > 0:
                        msg = "Negative indices reserved for special tokens"
                        assert dat.min() >= 0, msg
                        if self.skip_oov:
                            # Get Indexes of email and URL and oov tokens
                            idx = (dat[:, 1] > 0) | (dat[:, 2] > 0) | (dat[:, 3] > 0)
                        else:
                            # Get Indexes of email and URL tokens
                            idx = (dat[:, 1] > 0) | (dat[:, 2] > 0)                    
                        # Replace email and URL tokens with skip token
                        dat[idx] = self.skip
                        # Delete punctuation
                        if self.delete_punctuation:
                            delete = np.where(dat[:,3]==1)
                            dat = np.delete(dat, delete, 0)


                        length = min(len(dat), self.max_length)

                        # Get sentence token data
                        #sent_data[:length] = dat[:length, 0].ravel()
                        self.data[row, sent_idx, :length] = dat[:length, 0].ravel()
                        # Append sentence data to doc data
                        #doc_data.append(sent_data.tolist())

                except Exception as e:
                    #exc_type, exc_obj, exc_tb = sys.exc_info()
                    #fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    #print(row, exc_type, e, exc_tb.tb_lineno)
                    print("Warning! Document", row, "broke, likely due to spaCy merge issues.\nMore info at thier github, issues #1547 and #1474")
                    self.purged_docs.append(row)
                    continue
   
        if len(self.purged_docs) > 0:
            # If necessary, delete documents that failed to tokenize correctly.
            self.data = np.delete(self.data, self.purged_docs, 0).astype(np.uint64)

        self.uniques = np.array([], dtype=np.uint64)
        # Get unique data by any means necessary for now...
        for document in range(self.data.shape[0]):
            for sentence in range(self.data[document].shape[0]):
                self.uniques = np.append(self.uniques, self.data[document][sentence])

        # Unique tokens
        #self.uniques = np.unique(self.data.flatten())
        # Saved Spacy Vocab
        self.vocab = self.nlp.vocab
        # Making an idx to word mapping for vocab
        self.hash_to_word = {}
        # Manually putting in this hash for the padding ID
        self.hash_to_word[self.skip] = '<SKIP>'
        # If lemma, manually put in hash for the pronoun ID
        if self.token_type=="lemma":
            self.hash_to_word[self.nlp.vocab.strings["-PRON-"]] = "-PRON-"
        
        for v in self.uniques:
            if v!= self.skip:
                try:
                    if self.token_type == "lower":
                        self.hash_to_word[v] = self.nlp.vocab[v].lower_
                    elif self.token_type == "lemma":
                        self.hash_to_word[v] = self.nlp.vocab[v].lemma_
                    else:
                        self.hash_to_word[v] = self.nlp.vocab[v].orth_
                except:
                    pass

    def _compute_embed_matrix(self, random=False, embed_size=256, compute_tensor=False, tf_as_variable=True):
        """Computes the embedding matrix in a couple of ways. You can either initialize it randomly
        or you can load the embedding matrix from pretrained embeddings. 
        
        Additionally, you can use this function to compute your embedding matrix as a tensorflow
        variable or tensorflow constant.
        
        The numpy embedding matrix will be stored in self.embed_matrix
        The tensorflow embed matrix will be stored in self.embed_matrix_tensor if compute_tf is True
        
        Args:
            random (bool, optional): If set to true, it will initialize the embedding matrix randomly
            embed_size (int, optional): If setting up random embedding matrix, you can control the embedding size.
            compute_tensor (bool, optional): 
                When set to True, it will turn the embedding matrix into a tf variable or constant.
                See tf_as_variable to control whether embed_matrix_tensor is a variable or constant.
            tf_as_variable (bool, optional): If True AND compute_tf is True, this will save embed_matrix_tensor as a tf variable. 
                If this is set to False, it will compute embed_matrix_tensor as a tf constant.
        
        """
        #Returns list of values and their frequencies
        self.unique, self.freqs= np.unique(self.data, return_counts=True)

        ##Sort unique hash id values by frequency
        self.hash_ids = [x for _,x in sorted(zip(self.freqs, self.unique), reverse=True)]
        self.freqs = sorted(self.freqs, reverse=True)

        ##Create word id's starting at 0
        self.word_ids = np.arange(len(self.hash_ids))

        self.hash_to_idx = dict(zip(self.hash_ids, self.word_ids))
        self.idx_to_hash = dict(zip(self.word_ids, self.hash_ids))

        # Generate random embedding instead of using pretrained embeddings
        if random:
            self.embed_size = embed_size
            self.vocab_size = len(self.unique)
            self.embed_matrix = np.random.uniform(-1,1,[self.vocab_size, self.embed_size])
            if compute_tensor:
                self.compute_embedding_tensor(variable=tf_as_variable)
            return

        # Initialize vector of zeros to compare to OOV vectors (Which will be zero)
        zeros = np.zeros(300)
        # Initialize vector to hold our embedding matrix
        embed_matrix = []

        # Loop through hash IDs, they are in order of highest frequency to lowest
        for i, h in enumerate(self.hash_ids):
            # Extract vector for the given hash ID
            vector = self.nlp.vocab[h].vector

            # If the given vector is just zeros, it is out of vocabulary
            if np.array_equal(zeros, vector):
                # TODO Get rid of this random uniform vector!!
                # If oov, init a random uniform vector
                vector = np.random.uniform(-1,1,300)

            # Append current vector to our embed matrix         
            embed_matrix.append(vector)

        # Save np embed matrix to the class for later use
        self.embed_matrix = np.array(embed_matrix)

        if compute_tensor:
            self.compute_embedding_tensor(variable=tf_as_variable)


    def compute_embedding_tensor(self, variable=True):
        """Summary
        
        Args:
            variable (bool, optional): If variable is set to True, it will compute a tensorflow variable.
                                       If False, it will compute a tensorflow constant
        """
        # Create tensor and variable for use in tensorflow
        embed_matrix_tensor = tf.convert_to_tensor(self.embed_matrix)
        # Create embed matrix as tf variable
        if variable:
            self.embed_matrix_tensor = tf.Variable(embed_matrix_tensor)
        # Create embed matrix as tf constant
        else:
            self.embed_matrix_tensor = tf.Constant(embed_matrix_tensor)
    def convert_data_to_word2vec_indexes(self):
        # Uses hash to idx dictionary to map data to indexes
        self.idx_data = np.vectorize(self.hash_to_idx.get)(self.data)
    def trim_zeros_from_idx_data(self):
        """This will trim the tail zeros from the idx_data variable
        and replace the idx_data variable.
        """
        self.idx_data = np.array([np.trim_zeros(a, trim="b") for a in self.idx_data], dtype=np.int64)

    def save_nlp_object(self, nlp_object_path):
        self.nlp.to_disk(nlp_object_path)

    def hash_seq_to_words(self, seq):
        '''
        Pass this a single tokenized list of hash IDs and it will
        translate it to words!
        '''
        words = " "
        words = words.join([self.hash_to_word[seq[i]] for i in range(seq.shape[0])])
        return words

    def load_gensim_doc2vec(self, label=None, vector_size=128, window=5, min_count=5, workers=2):
        '''NOTE: To run this, make sure you had save_tokenized_text_data set to True when running tokenizer'''
        doc2vec_data = []
        
        # If user supplies labels (in same length as number of docs), we can use those
        if label == None:
            label = np.arange(len(self.text_data)).tolist()

        # Loop through text data and format it for doc2vec compatability
        for i, d in enumerate(self.text_data):
            doc2vec_data.append(TaggedDocument(d, [label[i]]))

        model = Doc2Vec(doc2vec_data,
                        vector_size=vector_size,
                        window=window,
                        min_count=min_count,
                        workers=workers)

        return model, doc2vec_data

    
    def make_example(self, sequence, context=None):
        # The object we return
        ex = tf.train.SequenceExample()
        # A non-sequential feature of our example - Replace with doc IDs
        if context==None:
            context = self.doc_id
        else:
            context = context
        # NOTICE: This is an integer value.
        # We will use these to supply doc context!!!
        ex.context.feature[self.context_desc].int64_list.value.append(context)
        # Feature lists for the two sequential features of our example
        fl_tokens = ex.feature_lists.feature_list[self.sequence_desc]
        for token in sequence:
            fl_tokens.feature.add().int64_list.value.append(token)
        return ex

    def make_example_with_labels(self, sequence, labels, context=None):
        # The object we return
        ex = tf.train.SequenceExample()
        # A non-sequential feature of our example - Replace with doc IDs
        if context==None:
            context = self.doc_id
        else:
            context = context
        # NOTICE: This is an integer value.
        # We will use these to supply doc context!!!
        ex.context.feature[self.context_desc].int64_list.value.append(context)
        # Feature lists for the two sequential features of our example
        fl_tokens = ex.feature_lists.feature_list[self.sequence_desc]
        fl_labels = ex.feature_lists.feature_list[self.labels_desc]
        for token, label in zip(sequence, labels):
            fl_tokens.feature.add().int64_list.value.append(token)
            fl_labels.feature.add().int64_list.value.append(label)
        return ex
    def write_data_to_tfrecords(self, outfile, compression="GZIP", data = np.array([]),
                                labels=np.array([]), context=np.array([]), sequence_desc = "tokens", labels_desc="labels", context_desc="doc_id"):
        if data.any()==False:
            data = self.idx_data

        # What we want the feature column for context features to be named
        self.context_desc = context_desc
        # What we want our sequence data feature column to be named
        self.sequence_desc = sequence_desc
        # If labels are provided, what is the feature column name of these labels?
        if labels.any():
            self.labels_desc = labels_desc
        # Create int to hold unique document IDs, as these will be our context feature by default.
        self.doc_id = 1

        if compression=="GZIP":
            options = tf.python_io.TFRecordOptions(tf.python_io.TFRecordCompressionType.GZIP)
        elif compression=="ZLIB":
            options = tf.python_io.TFRecordOptions(tf.python_io.TFRecordCompressionType.ZLIB)
        else:
            options = None

        # TODO - Test context. currently hasnt been tested
        with tf.python_io.TFRecordWriter(outfile, options=options) as writer:
            # Loop through data and create a serialized example for each
            for i, d in enumerate(data):
                # We get the serialized example based off of these two functions
                if labels.any():
                    if context.any():
                        # If we have labels, we pass those to this function
                        ex = self.make_example_with_labels(d, labels[i], context=context[i])
                    else:
                        ex = self.make_example_with_labels(d, labels[i])
                else:
                    if context.any():
                        # If we have labels, we pass those to this function
                        ex = self.make_example(d, context=context[i])
                    else:
                        ex = self.make_example(d)
                # Next, we write our serialized single example to file
                writer.write(ex.SerializeToString())

                # Add 1 to our document ID because we are moving to the next document
                self.doc_id += 1
