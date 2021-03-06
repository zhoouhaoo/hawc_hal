import numpy as np
import collections
import ROOT
ROOT.SetMemoryPolicy(ROOT.kMemoryStrict)

import root_numpy

from threeML.io.cern_root_utils.io_utils import get_list_of_keys, open_ROOT_file
from threeML.io.cern_root_utils.tobject_to_numpy import tree_to_ndarray
from threeML.io.file_utils import file_existing_and_readable, sanitize_filename

from tf1_wrapper import TF1Wrapper
from psf_fast import PSFWrapper


class ResponseBin(object):

    def __init__(self, open_ttree, dec_id, analysis_bin_id, log_log_spectrum, min_dec, dec_center, max_dec):

        # Save the dec boundaries
        self._min_dec = min_dec
        self._max_dec = max_dec
        self._dec_center = dec_center

        # Compute the labels as used in the response file
        dec_id_label = "dec_%02i" % dec_id
        analysis_bin_id_label = "nh_%02i" % analysis_bin_id

        # Read the histogram of the simulated events detected in this bin_name
        # NOTE: we do not copy this TH1D instance because we won't use it after the
        # file is closed

        en_sig_label = "EnSig_dec%i_nh%i" % (dec_id, analysis_bin_id)

        self._name = en_sig_label

        this_en_sig_th1d = open_ttree.Get("%s/%s/%s" % (dec_id_label, analysis_bin_id_label, en_sig_label))

        # The sum of the histogram is the total number of simulated events detected
        # in this analysis bin_name
        self._sim_n_sig_events = this_en_sig_th1d.Integral()

        # Get the content of the histogram as a numpy array
        self._en_sig_hist = root_numpy.hist2array(this_en_sig_th1d,
                                                  include_overflow=False,
                                                  copy=True,
                                                  return_edges=False)  # type: np.ndarray

        # Now let's see what has been simulated, i.e., the differential flux
        # at the center of each bin_name of the en_sig histogram
        self._en_sig_energy_centers = np.zeros(this_en_sig_th1d.GetNbinsX())
        self._en_sig_detected_counts = np.zeros_like(self._en_sig_energy_centers)
        self._en_sig_simulated_diff_fluxes = np.zeros_like(self._en_sig_energy_centers)

        for i in range(self._en_sig_energy_centers.shape[0]):
            # Remember: bin_name 0 is the underflow bin_name, that is why there
            # is a "i+1" and not just "i"
            bin_center = this_en_sig_th1d.GetBinCenter(i + 1)

            # Store the center of the logarithmic bin_name
            self._en_sig_energy_centers[i] = 10 ** bin_center  # TeV

            # Get from the simulated spectrum the value of the differential flux
            # at the center energy
            self._en_sig_simulated_diff_fluxes[i] = 10 ** log_log_spectrum(bin_center)  # TeV^-1 cm^-1 s^-1

            # Get from the histogram the detected events in each log-energy bin_name
            self._en_sig_detected_counts[i] = this_en_sig_th1d.GetBinContent(i + 1)

        # Read the histogram of the bkg events detected in this bin_name
        # NOTE: we do not copy this TH1D instance because we won't use it after the
        # file is closed

        en_bg_label = "EnBg_dec%i_nh%i" % (dec_id, analysis_bin_id)
        this_en_bg_th1d = open_ttree.Get("%s/%s/%s" % (dec_id_label, analysis_bin_id_label, en_bg_label))

        # The sum of the histogram is the total number of simulated events detected
        # in this analysis bin_name
        self._sim_n_bg_events = this_en_bg_th1d.Integral()

        # Now read the various TF1(s) for PSF, signal and background

        # Read the PSF and make a copy (so it will stay when we close the file)

        psf_label_tf1 = "PSF_dec%i_nh%i_fit" % (dec_id, analysis_bin_id)
        self._psf_fun = PSFWrapper(open_ttree.Get("%s/%s/%s" % (dec_id_label,
                                                                analysis_bin_id_label,
                                                                psf_label_tf1)))

        en_sig_label_tf1 = "EnSig_dec%i_nh%i_fit" % (dec_id, analysis_bin_id)
        self._en_sig_fun = TF1Wrapper(open_ttree.Get("%s/%s/%s" % (dec_id_label,
                                                                   analysis_bin_id_label,
                                                                   en_sig_label_tf1)))

        en_bg_label_tf1 = "EnBg_dec%i_nh%i_fit" % (dec_id, analysis_bin_id)
        self._en_bg_fun = TF1Wrapper(open_ttree.Get("%s/%s/%s" % (dec_id_label,
                                                                  analysis_bin_id_label,
                                                                  en_bg_label_tf1)))

    @property
    def name(self):
        return self._name

    @property
    def declination_boundaries(self):
        return (self._min_dec, self._max_dec)


    @property
    def declination_center(self):
        return self._dec_center

    @property
    def psf(self):

        return self._psf_fun

    @property
    def n_sim_signal_events(self):

        return self._sim_n_sig_events

    @property
    def n_sim_bkg_events(self):

        return self._sim_n_bg_events

    @property
    def sim_energy_bin_centers(self):

        return self._en_sig_energy_centers

    @property
    def sim_differential_photon_fluxes(self):

        return self._en_sig_simulated_diff_fluxes

    @property
    def sim_signal_events_per_bin(self):

        return self._en_sig_detected_counts



_instances = {}


def hawc_response_factory(response_file_name):
    """
    A factory function for the response which keeps a cache, so that the same response is not read over and
    over again.

    :param response_file_name:
    :return: an instance of HAWCResponse
    """

    # See if this response is in the cache, if not build it

    if not response_file_name in _instances:

        print("Creating singleton for %s" % response_file_name)

        new_instance = HAWCResponse(response_file_name)

        _instances[response_file_name] = new_instance

    # return the response, whether it was already in the cache or we just built it

    return _instances[response_file_name]  # type: HAWCResponse


class HAWCResponse(object):

    def __init__(self, response_file_name):

        # Make sure file is readable

        response_file_name = sanitize_filename(response_file_name)

        # Check that they exists and can be read

        if not file_existing_and_readable(response_file_name):

            raise IOError("Response %s does not exist or is not readable" % response_file_name)

        self._response_file_name = response_file_name

        # Read response

        with open_ROOT_file(response_file_name) as f:

            # Get the name of the trees
            object_names = get_list_of_keys(f)

            # Make sure we have all the things we need

            assert 'LogLogSpectrum' in object_names
            assert 'DecBins' in object_names
            assert 'AnalysisBins' in object_names

            # Read spectrum used during the simulation
            self._log_log_spectrum = TF1Wrapper(f.Get("LogLogSpectrum"))

            # Get the analysis bins definition
            dec_bins = tree_to_ndarray(f.Get("DecBins"))

            dec_bins_lower_edge = dec_bins['lowerEdge']  # type: np.ndarray
            dec_bins_upper_edge = dec_bins['upperEdge']  # type: np.ndarray
            dec_bins_center = dec_bins['simdec']  # type: np.ndarray

            self._dec_bins = zip(dec_bins_lower_edge, dec_bins_center, dec_bins_upper_edge)

            # Read in the ids of the response bins ("analysis bins" in LiFF jargon)
            response_bins_ids = tree_to_ndarray(f.Get("AnalysisBins"), "id")  # type: np.ndarray

            # Now we create a list of ResponseBin instances for each dec bin_name
            self._response_bins = collections.OrderedDict()

            for dec_id in range(len(self._dec_bins)):

                this_response_bins = []

                min_dec, dec_center, max_dec = self._dec_bins[dec_id]

                for response_bin_id in response_bins_ids:

                    this_response_bin = ResponseBin(f, dec_id, response_bin_id, self._log_log_spectrum,
                                                    min_dec, dec_center, max_dec)

                    this_response_bins.append(this_response_bin)

                self._response_bins[self._dec_bins[dec_id][1]] = this_response_bins

        del f

    def get_response_dec_bin(self, dec):

        # Find the closest dec bin_name. We iterate over all the dec bins because we don't want to assume
        # that the bins are ordered by Dec in the file (and the operation is very cheap anyway,
        # since the dec bins are few)

        dec_bins_keys = self._response_bins.keys()
        closest_dec_id = min(range(len(dec_bins_keys)), key=lambda i: abs(dec_bins_keys[i] - dec))

        return self._response_bins[dec_bins_keys[closest_dec_id]], closest_dec_id

    @property
    def dec_bins(self):

        return self._dec_bins

    @property
    def response_bins(self):

        return self._response_bins

    @property
    def n_energy_planes(self):

        return len(self._response_bins[0])

    def display(self):

        print("Response file: %s" % self._response_file_name)
        print("Number of dec bins: %s" % len(self._dec_bins))
        print("Number of energy/nHit planes per dec bin_name: %s" % (self.n_energy_planes))