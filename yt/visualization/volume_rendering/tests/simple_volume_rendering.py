"""
Run a simple volume rendering
"""

#-----------------------------------------------------------------------------
# Copyright (c) 2014, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------
import yt
from yt.testing import \
    fake_random_ds

ds = fake_random_ds(32)
im, sc = yt.volume_render(ds, fname='test.png', sigma_clip=4.0)
