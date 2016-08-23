"""
Unit test for the light_ray analysis module
"""

#-----------------------------------------------------------------------------
# Copyright (c) 2016, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import numpy as np

from yt.testing import \
    requires_file
from yt.analysis_modules.cosmological_observation.api import LightRay
import os
import shutil
from yt.utilities.answer_testing.framework import data_dir_load
import tempfile

COSMO_PLUS = "enzo_cosmology_plus/AMRCosmology.enzo"
COSMO_PLUS_SINGLE = "enzo_cosmology_plus/RD0009/RD0009"

@requires_file(COSMO_PLUS)
def test_light_ray_cosmo():
    """
    This test generates a cosmological light ray
    """
    # Set up in a temp dir
    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    lr = LightRay(COSMO_PLUS, 'Enzo', 0.0, 0.03)

    lr.make_light_ray(seed=1234567,
                      fields=['temperature', 'density', 'H_number_density'],
                      data_filename='lightray.h5')

    # clean up
    os.chdir(curdir)
    shutil.rmtree(tmpdir)

@requires_file(COSMO_PLUS)
def test_light_ray_cosmo_nested():
    """
    This test generates a cosmological light ray confing the ray to a subvolume
    """
    # Set up in a temp dir
    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    left = np.ones(3) * 0.25
    right = np.ones(3) * 0.75

    lr = LightRay(COSMO_PLUS, 'Enzo', 0.0, 0.03)

    lr.make_light_ray(seed=1234567, left_edge=left, right_edge=right,
                      fields=['temperature', 'density', 'H_number_density'],
                      data_filename='lightray.h5')

    # clean up
    os.chdir(curdir)
    shutil.rmtree(tmpdir)

@requires_file(COSMO_PLUS)
def test_light_ray_cosmo_nonperiodic():
    """
    This test generates a cosmological light ray using non-periodic segments
    """
    # Set up in a temp dir
    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    lr = LightRay(COSMO_PLUS, 'Enzo', 0.0, 0.03)

    lr.make_light_ray(seed=1234567, periodic=False,
                      fields=['temperature', 'density', 'H_number_density'],
                      data_filename='lightray.h5')

    # clean up
    os.chdir(curdir)
    shutil.rmtree(tmpdir)

@requires_file(COSMO_PLUS_SINGLE)
def test_light_ray_non_cosmo():
    """
    This test generates a non-cosmological light ray
    """

    # Set up in a temp dir
    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    lr = LightRay(COSMO_PLUS_SINGLE)

    ray_start = [0,0,0]
    ray_end = [1,1,1]
    lr.make_light_ray(start_position=ray_start, end_position=ray_end,
                      fields=['temperature', 'density', 'H_number_density'],
                      data_filename='lightray.h5')

    # clean up
    os.chdir(curdir)
    shutil.rmtree(tmpdir)

@requires_file(COSMO_PLUS_SINGLE)
def test_light_ray_non_cosmo_from_dataset():
    """
    This test generates a non-cosmological light ray created from an already
    loaded dataset
    """

    # Set up in a temp dir
    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    ds = data_dir_load(COSMO_PLUS_SINGLE)
    lr = LightRay(ds)

    ray_start = [0,0,0]
    ray_end = [1,1,1]
    lr.make_light_ray(start_position=ray_start, end_position=ray_end,
                      fields=['temperature', 'density', 'H_number_density'],
                      data_filename='lightray.h5')

    # clean up
    os.chdir(curdir)
    shutil.rmtree(tmpdir)

