"""
Unit test the ARMKDTree in yt.

Author: Samuel Skillman <samskillman@gmail.com>
Affiliation: University of Colorado at Boulder
Homepage: http://yt-project.org/
License:
  Copyright (C) 2013 Samuel Skillman.  All Rights Reserved.

  This file is part of yt.

  yt is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from yt.utilities.amr_kdtree.api import AMRKDTree
from yt.utilities.amr_kdtree.amr_kdtools import depth_traverse
import yt.utilities.initial_conditions as ic
import yt.utilities.flagging_methods as fm
from yt.frontends.stream.api import load_uniform_grid, refine_amr
from yt.testing import assert_equal
import numpy as np


def test_amr_kdtree_coverage():
    return #TESTDISABLED
    domain_dims = (32, 32, 32)
    data = np.zeros(domain_dims) + 0.25
    fo = [ic.CoredSphere(0.05, 0.3, [0.7, 0.4, 0.75],
                         {"Density": (0.25, 100.0)})]
    rc = [fm.flagging_method_registry["overdensity"](8.0)]
    ug = load_uniform_grid({'Density': data}, domain_dims, 1.0)
    pf = refine_amr(ug, rc, fo, 5)

    kd = AMRKDTree(pf)

    volume = kd.count_volume()
    yield assert_equal, volume, \
        np.prod(pf.domain_right_edge - pf.domain_left_edge)

    cells = kd.count_cells()
    true_cells = pf.h.all_data().quantities['TotalQuantity']('Ones')[0]
    yield assert_equal, cells, true_cells

    # This largely reproduces the AMRKDTree.tree.check_tree() functionality
    tree_ok = True
    for node in depth_traverse(kd.tree):
        if node.grid is None:
            continue
        grid = pf.h.grids[node.grid - kd._id_offset]
        dds = grid.dds
        gle = grid.LeftEdge
        li = np.rint((node.left_edge-gle)/dds).astype('int32')
        ri = np.rint((node.right_edge-gle)/dds).astype('int32')
        dims = (ri - li).astype('int32')
        tree_ok *= np.all(grid.LeftEdge <= node.left_edge)
        tree_ok *= np.all(grid.RightEdge >= node.right_edge)
        tree_ok *= np.all(dims > 0)

    yield assert_equal, True, tree_ok
