import scipy.spatial.qhull as qhull
import numpy as np
from hawc_hal.util import cartesian


def interp_weights(xy, uv, d=2):

    tri = qhull.Delaunay(xy)

    simplex = tri.find_simplex(uv)

    vertices = np.take(tri.simplices, simplex, axis=0)

    temp = np.take(tri.transform, simplex, axis=0)

    delta = uv - temp[:, d]

    bary = np.einsum('njk,nk->nj', temp[:, :d, :], delta)

    return vertices, np.hstack((bary, 1 - bary.sum(axis=1, keepdims=True)))


def interpolate(values, vtx, wts):

    return np.einsum('nj,nj->n', np.take(values, vtx), wts)



class FastLinearInterpolator(object):

    def __init__(self, data_shape, new_coords):

        old_coords = cartesian([np.arange(data_shape[0]), np.arange(data_shape[1])])

        self._vtx, self._wts = interp_weights(old_coords, new_coords)

    def __call__(self, data):

        return interpolate(data, self._vtx, self._wts)