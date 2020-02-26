#!/usr/bin/env python
# coding: utf-8

# # A short Tutorial to process sample NIRISS AMI simulations
# 
# * fit fringes for a simulated target and calibrator sequence (no WFE evolution between them)
# * calibrate target closure phases with the calibrator
# * fit for a binary

import glob
import os, sys, time
from astropy.io import fits
import numpy as np

from nrm_analysis import nrm_core, InstrumentData

import matplotlib.pyplot as plt
#get_ipython().run_line_magic('matplotlib', 'inline')

debug = True
home = os.path.expanduser('~')

np.set_printoptions(precision=4)
if debug:
    print("Current working directory is ", os.getcwd())
    print("InstrumentData is file: ", InstrumentData.__file__)

filt="F430M"

oversample = 3

# ### Where the data lives:

# small  disk, noise, call name different cos of central pix kluge, but it's correct.
# copied these from ami_sim output ~/scene_noise/..."
datadir = home+"/Downloads/asoulain_arch2019.12.07/Simulated_data/"
cr = "c_dsk_100mas__F430M_81_flat_x11__00_mir"
tr = "t_dsk_100mas__F430M_81_flat_x11__00_mir"
# Directories where ascii output files of fringe fitting will go:
tsavedir = datadir+"tgt_ov%d"%oversample
csavedir = datadir+"cal_ov%d"%oversample

test_tar = datadir + tr + ".fits"
test_cal = datadir + cr + ".fits"

if debug:
    print("tsavedir:", tsavedir, "\ntest_tar:", test_tar)
    print("csavedir:", csavedir, "\ntest_cal:", test_cal)

# ### First we specify the instrument & filter # (defaults: Spectral type set to A0V)
bp3= np.array([(0.1, 4.2e-6),(0.8, 4.3e-6),(0.1,4.4e-6)])
default = None
bpmono = np.array([(1.0, 4.3e-6),])
niriss = InstrumentData.NIRISS(filt, bandpass=default)

# ### Next: get fringe observables via image plane fringe-fitting
# * Need to pass the InstrumentData object, some keywords.
# * Files will be saved into specified directory + new directory named by filename

ff_t = nrm_core.FringeFitter(niriss, datadir=datadir, savedir=tsavedir, oversample=oversample, interactive=False) 
ff_c = nrm_core.FringeFitter(niriss, datadir=datadir, savedir=csavedir, oversample=oversample, interactive=False) 
#in general set interactive to False unless you really don't know what you are doing
                                                        
# This can take a little while -- there is a parallelization option, set threads=n_threads
# output of this is long -- may also want to do this scripted instead of in notebook,
# leaving off the output in this example.

ff_t.fit_fringes(test_tar)
ff_c.fit_fringes(test_cal)


# You'll find some new files. Text files save the observables you are trying to
# measure, but there are also some diagnostic fits files written: centered_X
# are the cropped/centered data, modelsolution_XX are the best fit model to the
# data, and residual_XX is the difference between the two. 

target_outputdir = tsavedir + "/" +  tr 
data =   fits.getdata(target_outputdir + "/centered_0.fits")
fmodel = fits.getdata(target_outputdir + "/modelsolution_01.fits")
res =    fits.getdata(target_outputdir + "/residual_01.fits")

plt.figure(figsize=(12,4))
plt.subplot(131)
plt.title("Input data")
im = plt.imshow(pow(data/data.max(), 0.5))
plt.axis("off")
plt.colorbar(fraction=0.046, pad=0.04)
plt.subplot(132)
plt.title("best model")
im = plt.imshow(pow(fmodel/data.max(), 0.5))
plt.axis("off")
plt.colorbar(fraction=0.046, pad=0.04)
plt.subplot(133)
plt.title("residual")
im = plt.imshow(res/data.max())
plt.axis("off")
plt.colorbar(fraction=0.046, pad=0.04)


# If you don't want to clog up your hardrive with fits files you can initialize
# FringeFitter with keyword "save_txt_only=True" -- but you may want to save
# out everything the first time you reduce the data to check it. Above we can
# see a pretty good fit the magnification of the model is a bit off. This shows
# up as a radial patter in the residual. Finely fitting the exact magnification
# and rotation should be done before fringe fitting. 

# ### Calibration is simple: point to the data
# 
# The most important thing is to pass the right InstrumentData object with
# correct parameters so wavelength, pixelscale, etc. can be interpreted into
# on-sky spatial frequency. This can write out an oifits file.

niriss.reset_nwav(1) # a kluge that replaces calling InstrumentData just to reset nwav to unity.
                     # Not sure why we need to do this.  Lower level code
                     # cleanup could in futurew obviate the necessity of doing this!

# Pass the location of where to save calibrated quantities as 'savedir' here:
calib = nrm_core.Calibrate((tsavedir+"/"+tr+"/", csavedir+"/"+cr+"/"), 
                           niriss, 
                           savedir = datadir, #####"calibrated_example/", 
                           interactive=False)
