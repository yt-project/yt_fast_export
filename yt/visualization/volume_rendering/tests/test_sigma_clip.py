"""
Test Simple Volume Rendering Scene

"""

#-----------------------------------------------------------------------------
# Copyright (c) 2014, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import os
import tempfile
import shutil
import yt
from yt.testing import fake_random_ds
from unittest import TestCase

# This toggles using a temporary directory. Turn off to examine images.
use_tmpdir = True


def setup():
    """Test specific setup."""
    from yt.config import ytcfg
    ytcfg["yt", "__withintesting"] = "True"


class SigmaClipTest(TestCase):
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

    def test_sigma_clip(self):
        ds = fake_random_ds(32)
        sc = yt.create_scene(ds)
        im = sc.render()
        sc.save('raw.png')
        sc.save('clip_2.png', sigma_clip=2)
        sc.save('clip_4.png', sigma_clip=4.0)
        print(sc)
        return im, sc
