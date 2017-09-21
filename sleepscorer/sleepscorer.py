# -*- coding: utf-8 -*-
"""
Created on Wed Sep  6 12:06:04 2017

@author: Simon
"""
import os
import keras
import numpy as np
import keras.backend as K
import matplotlib.pyplot as plt
from . import tools
from . import sleeploader


class Scorer(object):
    
    def __init__(self, files, cnn=None, rnn=None, channels=None, references=None, mapping=None, hypnograms=True):
        
        if cnn is None:
            self.cnn = './weights/cnn.hdf5'
            if not os.path.isfile('./weights/cnn.hdf5'):

                self.download_weights(cnn=True,rnn=False)
        if rnn is None:
            self.rnn = './weights/rnn.hdf5'
            if not os.path.isfile('./weights/rnn.hdf5'):
                self.download_weights(cnn=False,rnn=True)          
            
        self.files = files
        self.q = []
        self.channels = channels
        self.references = references
        self.hypnograms = hypnograms
    
    def _print(self, string):
        print(string)
    
    
    def add(self, eeg_file):
        if os.path.isfile(eeg_file):
            self.files.append(eeg_file)
        else:
            print('WARNING: Did not add, {} does not exist'.format(eeg_file))
            
    def download_weights(self, cnn = True, rnn = True):
        if cnn:
            if os.path.isfile(self.cnn):
                r = input('CNN Weights file already exists. Redownload? Y/N\n')
            else:
                r = input('CNN weights not found. Download weights (377 MB)?  Y/N\n')
            if r.upper() == 'Y':
                try: os.mkdir('./weights')
                except Exception: pass
                tools.download('https://www.dropbox.com/s/87jcp2zdqx833dd/cnn.hdf5?dl=1', './weights/cnn.hdf5')
            
        if rnn:
            if os.path.isfile(self.rnn):
                r = input('RNN Weights file already exists. Redownload? Y/N\n')
            else:
                r = input('RNN Weights not found. Download weights (14 MB)? Y/N\n')
            if r.upper() == 'Y':
                try: os.mkdir('./weights')
                except Exception: pass
                tools.download('https://www.dropbox.com/s/bx5ulz7ps3pyjbk/rnn.hdf5?dl=1', './weights/rnn.hdf5')
                
        
            
    def run(self):
        clf = Classifier()
        clf.load_cnn_model(self.cnn)
        clf.load_rnn_model(self.rnn)
        
        self.q = [x for x in self.files]
        self._print('Starting predictions of {} file(s)'.format(len(self.q)))
        while len(self.q) != 0:
            file = self.q.pop(0)
            if type(file)==str:
                self._print('Loading {}'.format(os.path.basename(file)))
                sleep = sleeploader.SleepData(file)()
                filename = file
            elif type(file)==sleeploader.SleepData:
                self._print('Loading {}'.format(os.path.basename(file.file)))
                sleep = file()
                filename = file.file
            else:
                raise TypeError('Type is {}, must be string or SleepData'.format(type(file)))
                
            self._print('Predicting...')
            preds = clf.predict(sleep, classes=True)
            np.savetxt(filename + '.csv', preds, fmt='%d')
            if self.hypnograms: 
                tools.plot_hypnogram(preds, title ='Predictions for {}'.format( os.path.basename(filename)))
                plt.savefig(filename + '.hyp.png')
                
        

            
            
            

            
class Classifier(object):

    def __init__(self, cnn_weights=False, rnn_weights=False, 
                wake = 0, s1 = 1, s2 = 2, sws = 3, rem = 4, verbose=1):
        """
        :param directory: a directory string
        """
        self.predictions = None
        self.mapping = {0:wake, 1:s1, 2:s2, 3:sws, 4:rem}
        self.verbose = verbose
        
        
    def _print(self, string):
        """
        Convenience function for printing. 
        Allows easy replacement of printing function or redirecting of streams.
        
        :param string: string to print
        """
        print(string)        
        
    def _get_activations(self, data, model, layers, batch_size=256):

        layer_list = []
        for layer in layers:
            if type(layer) is str:
                layer_list.append(model.get_layer(layer))
            elif type(layer) is int:
                layer_list.append(model.get_layer(index=layer))
            else:
                raise TypeError('Layername {} has type {}, must be str or int'.format(layer, type(layer)))
        inp = model.input                                           # input placeholder
        outputs = [layer.output for layer in layer_list]          # all layer outputs
        functor = K.function([inp] + [K.learning_phase()], outputs ) # evaluation function
        
        activations = [[] for x in layers]
        for i in range(int(np.ceil(len(data)/batch_size))):
            batch = np.array(data[i*batch_size:(i+1)*batch_size], dtype=np.float32)
            acts = functor([batch,0])
            for i in range(len(acts)):
                activations[i].append(acts[i])
        activations = [np.vstack(x).squeeze() for x in activations]
        
        return activations       


    def load_cnn_model(self, cnn_weights):
        if self.verbose == 1: self._print('Loading CNN model')
        self.cnn = keras.models.load_model(cnn_weights)
    
    
    def load_rnn_model(self, rnn_weights):
        if self.verbose == 1: self._print('Loading RNN model')
        self.rnn = keras.models.load_model(rnn_weights)
        
        
    def predict_cnn(self, data, layers=['fc1', -1], cropsize = 0, batch_size=256, modelpath = None):
        if modelpath is not None: self.load_cnn_model(modelpath)
        cropsize = self.cnn.input_shape[1]
        activations = self._get_activations(data[:,:cropsize,:], self.cnn, layers, batch_size=batch_size)
        if len(layers) == 2:
            features, predictions = activations
            self.features = features
            self.cnn_preds = predictions
            self.predict_rnn(features)
            return features, predictions
        else:
            self.cnn_preds = predictions
            return activations
    
    
    def predict_rnn(self, features, modelpath = None, batch_size=256):
        if modelpath is not None: self.load_rnn_model(modelpath)
        feat_seq = tools.to_sequences(features, seqlen = self.rnn.input_shape[1], tolist=False)
        preds = self.rnn.predict(feat_seq, batch_size=batch_size)
        return preds


    def predict(self, data, classes = True):
        if type(data) is sleeploader.SleepData: data=data()
        feats, cnn_preds = self.predict_cnn(data)
        rnn_preds = self.predict_rnn(feats)
        rnn_preds = np.roll(rnn_preds,-4, axis=0)
        preds = np.vstack([cnn_preds[:len(data)-len(rnn_preds)], rnn_preds]) # fill up missing RNN predictions with CNN preds
        print('Still rolling, I should fix that.')
        if classes:
            preds = np.argmax(preds,1)
            preds = [self.mapping[x] for x in preds]
        return preds        
        
    def get_classes(self):
        
        return np.argmax(self.predictions, 1)
    
    
    def get_probas(self):
        return self.predictions
    
    
    
    
    
    