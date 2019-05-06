import tensorflow as tf

from .dispatch import expectation_dispatcher
from .. import kernels
from .. import mean_functions as mfn
from ..features import InducingFeature, InducingPoints
from ..probability_distributions import (DiagonalGaussian, Gaussian,
                                         MarkovGaussian)
from ..util import NoneType
from .expectations import expectation


# ================ exKxz transpose and mean function handling =================

@expectation_dispatcher.register(MarkovGaussian, mfn.Identity, NoneType,
                                 kernels.Linear, InducingPoints)
@expectation_dispatcher.register(Gaussian, mfn.Identity, NoneType,
                                 kernels.Linear, InducingPoints)
def _E(p, mean, _, kernel, feature, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <x_n K_{x_n, Z}>_p(x_n)
        - K_{.,} :: Linear kernel
    or the equivalent for MarkovGaussian

    :return: NxDxM
    """
    return tf.linalg.adjoint(expectation(p, (kernel, feature), mean))


@expectation_dispatcher.register(MarkovGaussian, kernels.Kernel, InducingFeature,
                                 mfn.MeanFunction, NoneType)
@expectation_dispatcher.register(Gaussian, kernels.Kernel, InducingFeature,
                                 mfn.MeanFunction, NoneType)
def _E(p, kernel, feature, mean, _, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <K_{Z, x_n} m(x_n)>_p(x_n)
    or the equivalent for MarkovGaussian

    :return: NxMxQ
    """
    return tf.linalg.adjoint(expectation(p, mean, (kernel, feature), nghp=nghp))


@expectation_dispatcher.register(Gaussian, mfn.Constant, NoneType, kernels.Kernel, InducingPoints)
def _E(p, constant_mean, _, kernel, feature, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <m(x_n)^T K_{x_n, Z}>_p(x_n)
        - m(x_i) = c :: Constant function
        - K_{.,.}    :: Kernel function

    :return: NxQxM
    """
    c = constant_mean(p.mu)  # NxQ
    eKxz = expectation(p, (kernel, feature), nghp=nghp)  # NxM

    return c[..., None] * eKxz[:, None, :]


@expectation_dispatcher.register(Gaussian, mfn.Linear, NoneType, kernels.Kernel, InducingPoints)
def _E(p, linear_mean, _, kernel, feature, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <m(x_n)^T K_{x_n, Z}>_p(x_n)
        - m(x_i) = A x_i + b :: Linear mean function
        - K_{.,.}            :: Kernel function

    :return: NxQxM
    """
    N = p.mu.shape[0]
    D = p.mu.shape[1]
    exKxz = expectation(p, mfn.Identity(D), (kernel, feature), nghp=nghp)
    eKxz = expectation(p, (kernel, feature), nghp=nghp)
    eAxKxz = tf.linalg.matmul(tf.tile(linear_mean.A[None, :, :], (N, 1, 1)), exKxz,
                              transpose_a=True)
    ebKxz = linear_mean.b[None, :, None] * eKxz[:, None, :]
    return eAxKxz + ebKxz


@expectation_dispatcher.register(Gaussian, mfn.Identity, NoneType, kernels.Kernel, InducingPoints)
def _E(p, identity_mean, _, kernel, feature, nghp=None):
    """
    This prevents infinite recursion for kernels that don't have specific
    implementations of _expectation(p, identity_mean, None, kernel, feature).
    Recursion can arise because Identity is a subclass of Linear mean function
    so _expectation(p, linear_mean, none, kernel, feature) would call itself.
    More specific signatures (e.g. (p, identity_mean, None, RBF, feature)) will
    be found and used whenever available
    """
    raise NotImplementedError


# ============== Conversion to Gaussian from Diagonal or Markov ===============
# Catching missing DiagonalGaussian implementations by converting to full Gaussian:


@expectation_dispatcher.register(DiagonalGaussian,
                                 object, (InducingFeature, NoneType),
                                 object, (InducingFeature, NoneType))
def _E(p, obj1, feat1, obj2, feat2, nghp=None):
    gaussian = Gaussian(p.mu, tf.linalg.diag(p.cov))
    return expectation(gaussian, (obj1, feat1), (obj2, feat2), nghp=nghp)


# Catching missing MarkovGaussian implementations by converting to Gaussian (when indifferent):

@expectation_dispatcher.register(MarkovGaussian,
                                 object, (InducingFeature, NoneType),
                                 object, (InducingFeature, NoneType))
def _E(p, obj1, feat1, obj2, feat2, nghp=None):
    """
    Nota Bene: if only one object is passed, obj1 is
    associated with x_n, whereas obj2 with x_{n+1}

    """
    if obj2 is None:
        gaussian = Gaussian(p.mu[:-1], p.cov[0, :-1])
        return expectation(gaussian, (obj1, feat1), nghp=nghp)
    elif obj1 is None:
        gaussian = Gaussian(p.mu[1:], p.cov[0, 1:])
        return expectation(gaussian, (obj2, feat2), nghp=nghp)
    else:
        return expectation(p, (obj1, feat1), (obj2, feat2), nghp=nghp)