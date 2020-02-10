import os
import pathlib
import warnings
import numpy as np
from scipy.io import wavfile

from ..parameter import Parameter
from ..processor import Processor
from ..parameter_list import ParameterList

# Impulse responses
ir_dir = "irs"
src = {"sm-room" : "small_room.wav",
       "md-room" : "medium_room.wav",
       "lg-room" : "large_room.wav",
       "hall"    : "hall.wav",
       "plate"   : "plate.wav"}

class ConvolutionalReverb(Processor):
    def __init__(self, name="reverb", parameters=None, block_size=512, sample_rate=44100):

        super().__init__(name, parameters, block_size, sample_rate)

        if not parameters:
            self.parameters = ParameterList()
            self.parameters.add(Parameter("bypass",   False,   "bool", processor=None, p=0.1))
            self.parameters.add(Parameter("type", "sm-room", "string", processor=self, options=list(src.keys())))
            self.parameters.add(Parameter("decay",      1.0,  "float", processor=self, minimum=0.0, maximum=1.0))
            self.parameters.add(Parameter("dry_mix",    0.8,  "float", processor=self, minimum=0.0, maximum=1.0))
            self.parameters.add(Parameter("wet_mix",    0.1,  "float", processor=self, minimum=0.0, maximum=1.0))


        self.impulses = {}  # dict to store numpy array for each impulse response
        self.load()         # load all impulses into the dict
        self.update(None)   # pre-process current impulse ready for application

    def process(self, x):
        if self.parameters.bypass.value:
            return x
        else:
        
            if x.ndim < 2: # if input is mono (samples,) add stereo dim
                x = np.expand_dims(x, 1)    
            
            if x.shape[1] == 1: # if input is mono copy L to R        
                x = np.repeat(x, 2, axis=1)

            x = np.pad(x, ((0, self.block_size),(0,0))) # zero pad the input frame
            self.X = np.roll(self.X, 1, axis=2)         # make space for the new frame
            self.X[:,:,0] = np.fft.fft(x, axis=0)       # store the result of the fft for current frame
            Y = np.sum(self.X * self.H, axis=2)         # multiply inputs with filters
            y = np.real(np.fft.ifft(Y, axis=0))         # convert result to the time domain (only take real part)
            wet = y[:self.block_size] + self.overlap    # add the previous overlap to the output
            dry = x[:self.block_size,:]                 # grab the dry signal
            self.overlap = y[self.block_size:,:]        # store the overlap for the next frame

            wet *= self.parameters.wet_mix.value        # apply gain to wet signal
            dry *= self.parameters.dry_mix.value        # apply gain to input (dry) signal
            out = wet + dry                             # mix wet and dry signals

            return out

    def load(self):

        # read all impulse responses from disk and store
        for reverb in self.parameters.type.options:
            curdir = pathlib.Path(__file__).parent.absolute()
            filename = os.path.join(curdir, "..", ir_dir, src[self.parameters.type.value])

            sr, h = wavfile.read(filename)   # load the audio file for correct impulse response

            # check if the sample rate matches processor
            if sr != self.sample_rate:
                # for now we raise an error. but in the future we would want to automatically resample
                raise RuntimeError(f"Sample rate of impulse {sr} must match sample rate of processor {self.sample_rate}")

            h = h.astype(np.double)/(2**16)  # convert from 16 bit into to 64 bit float
            h *= 0.125                       # perform additional scaling for headroom
            self.impulses[reverb] = h        # store into dictionary

    def update(self, parameter_name):

        self.h = self.impulses[self.parameters.type.value].copy()

        # fade out the impulse based on the decay setting
        fstart = int(self.parameters.decay.value * self.h.shape[0])
        fstop  = np.min((self.h.shape[0], fstart + int(0.020*self.sample_rate))) # constant 50 ms fade out
        flen   = fstop - fstart

        # if there is a fade (i.e. decay < 1.0)
        if flen > 0:
            fade = np.arange(flen)/flen             # normalized set of indices
            fade = np.power(0.1, (1-fade) * 5)      # fade gain values with 100 dB of atten
            fade = np.expand_dims(fade, 1)          # add stereo dim
            fade = np.repeat(fade, 2, axis=1)       # copy gain to stereo dim
            self.h[fstart:fstop,:] *= fade          # apply fade
            self.h = self.h[:fstop]                 # throw away faded samples

        print("pre", self.h.shape)

        # pad the impulse to be divsibible by block size
        pad = self.block_size - (self.h.shape[0]%self.block_size)
        self.h = np.pad(self.h, ((0,pad),(0,0)))

        print("post", self.h.shape)

        # split the impulse into blocks of size block_size
        nfilters = self.h.shape[0]//self.block_size
        self.h_new = np.empty((self.block_size*2, self.h.shape[1], nfilters))

        # manually construct matrix of nfilters
        for n in np.arange(nfilters):
            start = n * self.block_size
            stop  = start + self.block_size
            # zero pad each chopped impulse at the end to block_size*2 
            self.h_new[:,:,n] = np.pad(self.h[start:stop,:], ((0, self.block_size),(0,0)))

        print("new", self.h_new.shape)

        self.h = self.h_new                                         # overwrite the unraveled impulse with the chopped one
        self.H = np.fft.fft(self.h, axis=0)                         # convert to freq domain filters
        X_init = np.zeros((self.h.shape))                           # create buffer to store past outputs in freq domai
        ovrlp_init = np.zeros((self.block_size, self.h.shape[1]))   # create buffer for the time-domain overlap signal
        self.X = np.fft.fft(X_init, axis=0)                         # convert zero values to freq domain
        self.overlap = ovrlp_init                                   # store zero values input buffer


