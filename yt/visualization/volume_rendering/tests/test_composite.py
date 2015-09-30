"""
Test for Composite VR.
"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import os
import tempfile
import shutil
from yt.testing import fake_random_ds
from yt.visualization.volume_rendering.api import Scene, Camera, \
    VolumeSource, LineSource, BoxSource
from yt.data_objects.api import ImageArray
import numpy as np
from unittest import TestCase

np.random.seed(0)

# This toggles using a temporary directory. Turn off to examine images.
use_tmpdir = True


def setup():
    """Test specific setup."""
    from yt.config import ytcfg
    ytcfg["yt", "__withintesting"] = "True"


class CompositeVRTest(TestCase):
    def setUp(self):
        if use_tmpdir:
            self.curdir = os.getcwd()
            # Perform I/O in safe place instead of yt main dir
            self.tmpdir = tempfile.mkdtemp()
            os.chdir(self.tmpdir)
        else:
            self.curdir, self.tmpdir = None, None

    def tearDown(self):
        if use_tmpdir:
            os.chdir(self.curdir)
            shutil.rmtree(self.tmpdir)

    def test_composite_vr(self):
        ds = fake_random_ds(64)
        dd = ds.sphere(ds.domain_center, 0.45*ds.domain_width[0])
        ds.field_info[ds.field_list[0]].take_log=False

        sc = Scene()
        cam = Camera(ds)
        cam.resolution = (512, 512)
        sc.camera = cam
        vr = VolumeSource(dd, field=ds.field_list[0])
        vr.transfer_function.clear()
        vr.transfer_function.grey_opacity=True
        vr.transfer_function.map_to_colormap(0.0, 1.0, scale=3.0, colormap="Reds")
        sc.add_source(vr)

        cam.set_width( 1.8*ds.domain_width )
        cam.lens.setup_box_properties(cam)

        # DRAW SOME LINES
        npoints = 100
        vertices = np.random.random([npoints, 2, 3])
        colors = np.random.random([npoints, 4])
        colors[:, 3] = 0.10

        box_source = BoxSource(ds.domain_left_edge, 
                               ds.domain_right_edge, 
                               color=[1.0, 1.0, 1.0, 1.0])
        sc.add_source(box_source)

        LE = ds.domain_left_edge + np.array([0.1,0.,0.3])*ds.domain_left_edge.uq
        RE = ds.domain_right_edge-np.array([0.1,0.2,0.3])*ds.domain_left_edge.uq
        color = np.array([0.0, 1.0, 0.0, 0.10])
        box_source = BoxSource(LE, RE, color=color)
        sc.add_source(box_source)

        line_source = LineSource(vertices, colors)
        sc.add_source(line_source)

        im = sc.render()
        im = ImageArray(im.d)
        im.write_png("composite.png")
        return im
