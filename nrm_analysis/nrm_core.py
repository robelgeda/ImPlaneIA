#! /usr/bin/env python

"""
by A. Greenbaum & A. Sivaramakrishnan 
April 2016 agreenba@pha.jhu.edu

Contains 

FringeFitter - fit fringe phases and amplitudes to data in the image plane

Calibrate - Calibrate target data with calibrator data

BinaryAnalyze - Detection, mcmc modeling, visualization tools
                Much of this section is based on tools in the pymask code
                by F. Martinache, B. Pope, and A. Cheetham
                We especially thank A. Cheetham for help and advising for
                developing the analysis tools in this package. 

    LG++ anand@stsci.edu nrm_core changes:
        Removed use of 'centering' parameter, switch to psf_offsets, meant to be uniformly ds9-compatible 
        offsets from array center (regardless of even/odd array sizes).

            nrm_core.fit_image(): refslice UNTESTED w/ new utils.centroid()
            nrm_core.fit_image(): hold_centering UNTESTED w/ new utils.centroid()

"""


from __future__ import print_function
# Standard imports
import os, sys, time
import numpy as np
from astropy.io import fits
from scipy.special import comb
from scipy.stats import sem, mstats
import pickle as pickle
import matplotlib.pyplot as plt


# Module imports
from nrm_analysis.fringefitting.LG_Model import NRM_Model
from nrm_analysis.misctools import utils  # AS LG++
from nrm_analysis.misctools import implane2oifits 
from nrm_analysis.modeling.binarymodel import model_cp_uv, model_allvis_uv, model_v2_uv, model_t3amp_uv
from nrm_analysis.modeling.multimodel import model_bispec_uv

from multiprocessing import Pool

class FringeFitter:
    def __init__(self, instrument_data, **kwargs):
        """
        Fit fringes in the image plane

        Takes an instance of the appropriate instrument class
        Various options can be set

        kwarg options:
        oversample - model oversampling (also how fine to measure the centering)
        psf_offset - If you already know the subpixel centering of your data, give it here
                     (not recommended except when debugging with perfectly know image placement))
        outdir - Where text observables, derived fits files will get saved.  Default is working directory.
        oifdir - Where raw oifits files will get saved.  Default is working directory.
        npix - How many pixels of your data do you want to use? 
               Default is the shape of a data [slice or frame].  Typically odd?
        debug - will plot the FT of your data next to the FT of a reference PSF.
                Needs poppy package to run
        verbose_save - saves more than the standard files
        interactive - default True, prompts user to overwrite/create fresh directory.  
                      False will overwrite files where necessary.
        find_rotation - will find the best pupil rotation that matches the data
        verbose - T/F

        main method:
        * fit_fringes


        """
        self.instrument_data = instrument_data

        #######################################################################
        # Options
        self.oversample = 3
        if "oversample" in kwargs:
            self.oversample = kwargs["oversample"]

        self.find_rotation = False
        if "find_rotation" in kwargs:
            # can be True/False or 1/0
            self.find_rotation = kwargs["find_rotation"]

        self.psf_offset_ff = None #find center of image in data
        if "psf_offset_ff" in kwargs: # if so do not find center of image in data
            self.psf_offset_ff = kwargs["psf_offset_ff"]         

        if "outdir" in kwargs:  # write OI text files here, [diagnostic images fits]. Was 'savedir'
            self.outdir = kwargs["outdir"]
        elif 'savedir' in kwargs:
            self.outdir = kwargs["savedir"]
            print("nrm_core.FringeFitter: savedir deprecated but will be used for outdir variable.")
        else:
            print(   "nrm_core.FringeFitter: Fatal:  must specify outdir.")
            sys.exit("nrm_core.FringeFitter:         outdir: directory for text output OI files & diagnostic fits images.")
        if self.outdir[-1] != '/': self.outdir = self.outdir + '/'

        if "oifdir" in kwargs:  # where oifits raw files will get saved
            self.oifdir = kwargs["oifdir"]
        else:
            print(   "nrm_core.FringeFitter: Fatal:  must specify oifdir.")
            sys.exit("nrm_core.FringeFitter:         oifdir: directory for oifits files.")
        if self.oifdir[-1] != '/': self.oifdir = self.oifdir + '/'

        self.npix = 'default'
        if "npix" in kwargs:
            self.npix = kwargs["npix"]

        self.debug=False
        if "debug" in kwargs:
            self.debug=kwargs["debug"]

        self.verbose_save = False
        if "verbose_save" in kwargs:
            self.verbose_save = kwargs["verbose_save"]

        self.interactive = True
        if 'interactive' in kwargs:
            self.interactive = kwargs['interactive']

        self.save_txt_only = False
        if "save_txt_only" in kwargs:
            self.save_txt_only = kwargs["save_txt_only"]

        self.verbose = False
        if "verbose" in kwargs:
            self.verbose = kwargs["verbose"]
        #######################################################################


        #######################################################################
        # Create directories if they don't already exist
        try:
            os.mkdir(self.outdir)
        except:
            if self.interactive is True:
                print(self.outdir+" Already exists, rewrite its contents? (y/n)")
                ans = input()
                if ans == "y":
                    pass
                elif ans == "n":
                    sys.exit("use alternative save directory with kwarg 'outdir' when calling FringeFitter")
                else:
                    sys.exit("Invalid answer. Stopping.")
            else:
                pass

    ###
    # May 2017 J Sahlmann updates: parallelized fringe-fitting
    # Feb 2021 anand added bpdata to fringe fitting
    ###

    def fit_fringes(self, fns, threads = 0):
        if type(fns) == str:
            fns = [fns, ]

        # Can get fringes for images in parallel
        store_dict = [{"object":self, "file":fn,"id":jj} \
                        for jj,fn in enumerate(fns)]

        t2 = time.time()
        for jj, fn in enumerate(fns):
            fit_fringes_parallel({"object":self, "file":fn,\
                                  "id":jj},threads)
        t3 = time.time()
        print("Parallel with {0} threads took {1:.2f}s to fit all fringes".format(\
               threads, t3-t2))

        print("\tnrm_core.ff(): self.instrument_data.outdir:", self.instrument_data.outdir)
        print("\tnrm_core.ff():                 self.outdir:", self.outdir)
        print("\tnrm_core.ff:                   self.oifdir ", self.oifdir)
        print("\tnrm_core.ff():                    oitxtdir:", self.outdir+self.instrument_data.outdir)
        # Read in all relevant text observables and save to oifits file...
        dct = implane2oifits.oitxt2oif(nh=7, oitxtdir=self.outdir+self.instrument_data.outdir+'/' ,
                                             oifdir=self.oifdir,
                                             verbose=self.verbose,
                                             )


    def save_output(self, slc, nrm):
        # cropped & centered PSF
        self.datapeak = self.ctrd.max()
        #TBD: Keep only n_*.fits files after testing is done and before doing ImPlaneIA delivery
        if self.save_txt_only == False:
            fits.PrimaryHDU(data=self.ctrd, \
                    header=self.scihdr).writeto(self.outdir+\
                    self.sub_dir_str+"/centered_{0}.fits".format(slc), \
                    overwrite=True)
            fits.PrimaryHDU(data=self.ctrd/self.datapeak, \
                    header=self.scihdr).writeto(self.outdir+\
                    self.sub_dir_str+"/n_centered_{0}.fits".format(slc), \
                    overwrite=True)

            model, modelhdu = nrm.plot_model(fits_true=1)
            # save to fits files
            fits.PrimaryHDU(data=nrm.residual).writeto(self.outdir+\
                        self.sub_dir_str+"/residual_{0:02d}.fits".format(slc), \
                        overwrite=True)
            fits.PrimaryHDU(data=nrm.residual/self.datapeak).writeto(self.outdir+\
                        self.sub_dir_str+"/n_residual_{0:02d}.fits".format(slc), \
                        overwrite=True)
            modelhdu.writeto(self.outdir+\
                        self.sub_dir_str+"/modelsolution_{0:02d}.fits".format(slc),\
                        overwrite=True)
            fits.PrimaryHDU(data=model/self.datapeak, \
                    header=modelhdu.header).writeto(self.outdir+\
                    self.sub_dir_str+"/n_modelsolution_{0:02d}.fits".format(slc), \
                    overwrite=True)
            try: # if there's an appropriately trimmed bad pixel map write it out
                fits.PrimaryHDU(data=self.ctrb, \
                    header=self.scihdr).writeto(self.outdir+\
                    self.sub_dir_str+"/bp_{0}.fits".format(slc), \
                    overwrite=True)
            except: AttributeError
                

        # default save to text files
        np.savetxt(self.outdir+self.sub_dir_str + \
                   "/solutions_{0:02d}.txt".format(slc), nrm.soln)
        np.savetxt(self.outdir+self.sub_dir_str + \
                   "/phases_{0:02d}.txt".format(slc), nrm.fringephase)
        np.savetxt(self.outdir+self.sub_dir_str + \
                   "/amplitudes_{0:02d}.txt".format(slc), nrm.fringeamp)
        np.savetxt(self.outdir+self.sub_dir_str + \
                   "/CPs_{0:02d}.txt".format(slc), nrm.redundant_cps)
        np.savetxt(self.outdir+self.sub_dir_str + \
                   "/CAs_{0:02d}.txt".format(slc), nrm.redundant_cas)
        np.savetxt(self.outdir+self.sub_dir_str + \
                  "/fringepistons_{0:02d}.txt".format(slc), nrm.fringepistons)

        # write info that oifits wants only when writing out first slice.
        # this will relevant to all slices... so no slice number here.
        if slc == 0:
            pfn = self.outdir+self.sub_dir_str + "/info4oif_dict.pkl"
            pfd = open(pfn, 'wb')
            pickle.dump(self.instrument_data.info4oif_dict, pfd)
            pfd.close()

        # optional save outputs
        if self.verbose_save:
            np.savetxt(self.outdir+self.sub_dir_str+\
                       "/condition_{0:02d}.txt".format(slc), nrm.cond)
            np.savetxt(self.outdir+self.sub_dir_str+\
                       "/flux_{0:02d}.txt".format(slc), nrm.flux)
          
        #print(nrm.linfit_result)
        if nrm.linfit_result is not None:          
            # save linearfit results to pickle file
            myPickleFile = os.path.join(self.outdir+self.sub_dir_str,
                                        "linearfit_result_{0:02d}.pkl".format(slc))
            with open( myPickleFile , "wb" ) as f:
                pickle.dump((nrm.linfit_result), f) 
            print("Wrote pickled file  %s" % myPickleFile)
                       

    def save_auto_figs(self, slc, nrm):
        
        # rotation
        if self.find_rotation==True:
            plt.figure()
            plt.plot(nrm.rots, nrm.corrs)
            plt.vlines(nrm.rot_measured, nrm.corrs[0],
                        nrm.corrs[-1], linestyles='--', color='r')
            plt.text(nrm.rots[1], nrm.corrs[1], 
                     "best fit at {0}".format(nrm.rot_measured))
            plt.savefig(self.outdir+self.sub_dir_str+\
                        "/rotationcorrelation_{0:02d}.png".format(slc))

def fit_fringes_parallel(args, threads):
    self = args['object']
    filename = args['file']
    id_tag = args['id']
    self.prihdr, self.scihdr, self.scidata, self.bpdata = self.instrument_data.read_data(filename)
    self.sub_dir_str = self.instrument_data.outdir
    try:
        os.mkdir(self.outdir+self.sub_dir_str)
    except:
        pass

    store_dict = [{"object":self, "slc":slc} for slc in \
                  range(self.instrument_data.nwav)]

    if threads>0:
        pool = Pool(processes=threads)
        print("Running fit_fringes in parallel with {0} threads".format(threads))
        pool.map(fit_fringes_single_integration, store_dict)
        pool.close()
        pool.join()

    else:
        for slc in range(self.instrument_data.nwav):
            fit_fringes_single_integration({"object":self, "slc":slc})

def fit_fringes_single_integration(args):
    self = args["object"]
    slc = args["slc"]  # indexes each slice of 3D stack of images
    id_tag = args["slc"]
    nrm = NRM_Model(mask=self.instrument_data.mask,
                    pixscale=self.instrument_data.pscale_rad,
                    holeshape=self.instrument_data.holeshape,
                    affine2d=self.instrument_data.affine2d,
                    over = self.oversample)

    # for image data from single filter, this is the filter bandpass.
    # otherwise it's the IFU wavelength slice.
    nrm.bandpass = self.instrument_data.wls[slc]

    if self.npix == 'default':
        self.npix = self.scidata[slc,:,:].shape[0]
    
    # New or modified in LG++
    # center the image on its peak pixel:
    # AS subtract 1 from "r" below  for testing >1/2 pixel offsets
    # AG 03-2019 -- is above comment still relevant?
    
    # Where appropriate, the slice under consideration is centered, and processed
    if self.instrument_data.arrname=="NIRC2_9NRM":
        self.ctrd = utils.center_imagepeak(self.scidata[slc,:,:], 
                        r = (self.npix -1)//2 - 2, cntrimg=False)  
    elif self.instrument_data.arrname=="gpi_g10s40":
        self.ctrd = utils.center_imagepeak(self.scidata[slc,:,:], 
                        r = (self.npix -1)//2 - 2, cntrimg=True)  
    elif self.instrument_data.arrname=="jwst_g7s6c":
        # get the cropped image and identically-cropped bad pixel data:
        self.ctrd, self.ctrb = utils.center_imagepeak(self.scidata[slc,:,:], bpd=self.bpdata[slc,:,:]) 
    else:
        self.ctrd = utils.center_imagepeak(self.scidata[slc,:,:])  
    

    # store the 2D cropped image centered on the brightest pixel, bad pixels smoothed over
    #nrm.reference = self.ctrd  # self.ctrd is the cropped image centered on the brightest pixel

    if self.psf_offset_ff is None:
        # returned values have offsets x-y flipped:
        # Finding centroids the Fourier way assumes no bad pixels case - Fourier domain mean slope
        centroid = utils.find_centroid(self.ctrd, self.instrument_data.threshold) # offsets from brightest pixel ctr
        # use flipped centroids to update centroid of image for JWST - check parity for GPI, Vizier,...
        # pixel coordinates: - note the flip of [0] and [1] to match DS9 view
        image_center = utils.centerpoint(self.ctrd.shape) + np.array((centroid[1], centroid[0])) # info only, unused
        nrm.xpos = centroid[1]  # flip 0 and 1 to convert
        nrm.ypos = centroid[0]  # flip 0 and 1
        nrm.psf_offset = nrm.xpos, nrm.ypos  # renamed .bestcenter to .psf_offset
        if self.debug: print("nrm.core.fit_fringes_single_integration: utils.find_centroid() -> nrm.psf_offset")
    else:
        nrm.psf_offset = self.psf_offset_ff # user-provided psf_offset python-style offsets from array center are here.


    nrm.make_model(fov=self.ctrd.shape[0], 
                   bandpass=nrm.bandpass, 
                   over=self.oversample,
                   psf_offset=nrm.psf_offset,  
                   pixscale=nrm.pixel)
    # again, fit just one slice...
    if self.instrument_data.arrname=="jwst_g7s6c":
        nrm.fit_image(self.ctrd, modelin=nrm.model, psf_offset=nrm.psf_offset, bpd=self.ctrb)
    else:
        nrm.fit_image(self.ctrd, modelin=nrm.model, psf_offset=nrm.psf_offset)

    """
    Attributes now stored in nrm object:

    -----------------------------------------------------------------------------
    soln            --- resulting sin/cos coefficients from least squares fitting
    fringephase     --- baseline phases in radians
    fringeamp       --- baseline amplitudes (flux normalized)
    redundant_cps   --- closure phases in radians
    redundant_cas   --- closure amplitudes
    residual        --- fit residuals [data - model solution]
    cond            --- matrix condition for inversion
    fringepistons   --- zero-mean piston opd in radians on each hole (eigenphases)
    -----------------------------------------------------------------------------
    For jwst_g7s6 cropped-to-match-data bad pixel array 'ctrb' is also stored
    """

    self.save_output(slc, nrm)
    self.nrm = nrm # store  extracted values here
    return None
