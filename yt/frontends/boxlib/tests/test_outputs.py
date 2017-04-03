"""
Boxlib frontend tests



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2017, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from yt.testing import \
    assert_equal, \
    requires_file, \
    units_override_check
from yt.utilities.answer_testing.framework import \
    requires_ds, \
    small_patch_amr, \
    data_dir_load
from yt.frontends.boxlib.api import \
    OrionDataset, \
    NyxDataset, \
    WarpXDataset, \
    CastroDataset
import numpy as np    

# We don't do anything needing ghost zone generation right now, because these
# are non-periodic datasets.
_orion_fields = ("temperature", "density", "velocity_magnitude")
_nyx_fields = ("Ne", "Temp", "particle_mass_density")
_warpx_fields = ("Ex", "By", "jz")
_castro_fields = ("Temp", "density", "particle_count")

radadvect = "RadAdvect/plt00000"
@requires_ds(radadvect)
def test_radadvect():
    ds = data_dir_load(radadvect)
    yield assert_equal, str(ds), "plt00000"
    for test in small_patch_amr(ds, _orion_fields):
        test_radadvect.__name__ = test.description
        yield test

rt = "RadTube/plt00500"
@requires_ds(rt)
def test_radtube():
    ds = data_dir_load(rt)
    yield assert_equal, str(ds), "plt00500"
    for test in small_patch_amr(ds, _orion_fields):
        test_radtube.__name__ = test.description
        yield test

star = "StarParticles/plrd01000"
@requires_ds(star)
def test_star():
    ds = data_dir_load(star)
    yield assert_equal, str(ds), "plrd01000"
    for test in small_patch_amr(ds, _orion_fields):
        test_star.__name__ = test.description
        yield test

LyA = "Nyx_LyA/plt00000"
@requires_ds(LyA)
def test_LyA():
    ds = data_dir_load(LyA)
    yield assert_equal, str(ds), "plt00000"
    for test in small_patch_amr(ds, _nyx_fields,
                                input_center="c",
                                input_weight="Ne"):
        test_LyA.__name__ = test.description
        yield test

@requires_file(LyA)
def test_nyx_particle_io():
    ds = data_dir_load(LyA)

    grid = ds.index.grids[0]
    npart_grid_0 = 7908  # read directly from the header
    assert_equal(grid['particle_position_x'].size, npart_grid_0)
    assert_equal(grid['DM', 'particle_position_y'].size, npart_grid_0)
    assert_equal(grid['all', 'particle_position_z'].size, npart_grid_0)

    ad = ds.all_data()
    npart = 32768  # read directly from the header
    assert_equal(ad['particle_velocity_x'].size, npart)
    assert_equal(ad['DM', 'particle_velocity_y'].size, npart)
    assert_equal(ad['all', 'particle_velocity_z'].size, npart)

    assert(np.all(ad['particle_mass'] == ad['particle_mass'][0]))

    left_edge = ds.arr([0.0, 0.0, 0.0], 'code_length')
    right_edge = ds.arr([4.0, 4.0, 4.0], 'code_length')
    center = 0.5*(left_edge + right_edge)
                   
    reg = ds.region(center, left_edge, right_edge)

    assert(np.all(np.logical_and(reg['particle_position_x'] <= right_edge[0], 
                                 reg['particle_position_x'] >= left_edge[0])))

    assert(np.all(np.logical_and(reg['particle_position_y'] <= right_edge[1], 
                                 reg['particle_position_y'] >= left_edge[1])))

    assert(np.all(np.logical_and(reg['particle_position_z'] <= right_edge[2], 
                                 reg['particle_position_z'] >= left_edge[2])))

RT_particles = "RT_particles/plt00050"
@requires_ds(RT_particles)
def test_RT_particles():
    ds = data_dir_load(RT_particles)
    yield assert_equal, str(ds), "plt00050"
    for test in small_patch_amr(ds, _castro_fields):
        test_RT_particles.__name__ = test.description
        yield test


@requires_file(RT_particles)
def test_castro_particle_io():
    ds = data_dir_load(RT_particles)

    grid = ds.index.grids[2]
    npart_grid_2 = 49  # read directly from the header
    assert_equal(grid['particle_position_x'].size, npart_grid_2)
    assert_equal(grid['Tracer', 'particle_position_y'].size, npart_grid_2)
    assert_equal(grid['all', 'particle_position_y'].size, npart_grid_2)

    ad = ds.all_data()
    npart = 49  # read directly from the header
    assert_equal(ad['particle_velocity_x'].size, npart)
    assert_equal(ad['Tracer', 'particle_velocity_y'].size, npart)
    assert_equal(ad['all', 'particle_velocity_y'].size, npart)

    left_edge = ds.arr([0.0, 0.0, 0.0], 'code_length')
    right_edge = ds.arr([0.25, 1.0, 1.0], 'code_length')
    center = 0.5*(left_edge + right_edge)
                   
    reg = ds.region(center, left_edge, right_edge)

    assert(np.all(np.logical_and(reg['particle_position_x'] <= right_edge[0], 
                                 reg['particle_position_x'] >= left_edge[0])))

    assert(np.all(np.logical_and(reg['particle_position_y'] <= right_edge[1], 
                                 reg['particle_position_y'] >= left_edge[1])))

langmuir = "LangmuirWave/plt00020_v2"
@requires_ds(langmuir)
def test_langmuir():
    ds = data_dir_load(langmuir)
    yield assert_equal, str(ds), "plt00020_v2"
    for test in small_patch_amr(ds, _warpx_fields, 
                                input_center="c",
                                input_weight="Ex"):
        test_langmuir.__name__ = test.description
        yield test

plasma = "PlasmaAcceleration/plt00030_v2"
@requires_ds(plasma)
def test_plasma():
    ds = data_dir_load(plasma)
    yield assert_equal, str(ds), "plt00030_v2"
    for test in small_patch_amr(ds, _warpx_fields,
                                input_center="c",
                                input_weight="Ex"):
        test_plasma.__name__ = test.description
        yield test

@requires_file(plasma)
def test_warpx_particle_io():
    ds = data_dir_load(plasma)
    grid = ds.index.grids[0]

    # read directly from the header
    npart0_grid_0 = 344  
    npart1_grid_0 = 69632

    assert_equal(grid['particle0', 'particle_position_x'].size, npart0_grid_0)
    assert_equal(grid['particle1', 'particle_position_y'].size, npart1_grid_0)
    assert_equal(grid['all', 'particle_position_z'].size, npart0_grid_0 + npart1_grid_0)

    # read directly from the header
    npart0 = 1360  
    npart1 = 802816  
    ad = ds.all_data()
    assert_equal(ad['particle0', 'particle_velocity_x'].size, npart0)
    assert_equal(ad['particle1', 'particle_velocity_y'].size, npart1)
    assert_equal(ad['all', 'particle_velocity_z'].size, npart0 + npart1)

    np.all(ad['particle1', 'particle_mass'] == ad['particle1', 'particle_mass'][0])
    np.all(ad['particle0', 'particle_mass'] == ad['particle0', 'particle_mass'][0])

    left_edge = ds.arr([-7.5e-5, -7.5e-5, -7.5e-5], 'code_length')
    right_edge = ds.arr([2.5e-5, 2.5e-5, 2.5e-5], 'code_length')
    center = 0.5*(left_edge + right_edge)
                   
    reg = ds.region(center, left_edge, right_edge)

    assert(np.all(np.logical_and(reg['particle_position_x'] <= right_edge[0], 
                                 reg['particle_position_x'] >= left_edge[0])))

    assert(np.all(np.logical_and(reg['particle_position_y'] <= right_edge[1], 
                                 reg['particle_position_y'] >= left_edge[1])))

    assert(np.all(np.logical_and(reg['particle_position_z'] <= right_edge[2], 
                                 reg['particle_position_z'] >= left_edge[2])))

@requires_file(rt)
def test_OrionDataset():
    assert isinstance(data_dir_load(rt), OrionDataset)

@requires_file(LyA)
def test_NyxDataset():
    assert isinstance(data_dir_load(LyA), NyxDataset)

@requires_file(RT_particles)
def test_CastroDataset():
    assert isinstance(data_dir_load(RT_particles), CastroDataset)

@requires_file(LyA)
def test_WarpXDataset():
    assert isinstance(data_dir_load(plasma), WarpXDataset)

@requires_file(rt)
def test_units_override():
    for test in units_override_check(rt):
        yield test

nyx_no_particles = "nyx_sedov_plt00086"
@requires_file(nyx_no_particles)
def test_nyx_no_part():
    assert isinstance(data_dir_load(nyx_no_particles), NyxDataset)

    fields = sorted(
        [('boxlib', 'H'), ('boxlib', 'He'), ('boxlib', 'MachNumber'),
         ('boxlib', 'Ne'), ('boxlib', 'Rank'), ('boxlib', 'StateErr'),
         ('boxlib', 'Temp'), ('boxlib', 'X(H)'), ('boxlib', 'X(He)'),
         ('boxlib', 'density'), ('boxlib', 'divu'), ('boxlib', 'eint_E'),
         ('boxlib', 'eint_e'), ('boxlib', 'entropy'), ('boxlib', 'forcex'),
         ('boxlib', 'forcey'), ('boxlib', 'forcez'), ('boxlib', 'kineng'),
         ('boxlib', 'logden'), ('boxlib', 'magmom'), ('boxlib', 'magvel'),
         ('boxlib', 'magvort'), ('boxlib', 'pressure'), ('boxlib', 'rho_E'),
         ('boxlib', 'rho_H'), ('boxlib', 'rho_He'), ('boxlib', 'rho_e'),
         ('boxlib', 'soundspeed'), ('boxlib', 'x_velocity'), ('boxlib', 'xmom'),
         ('boxlib', 'y_velocity'), ('boxlib', 'ymom'), ('boxlib', 'z_velocity'),
         ('boxlib', 'zmom')])

    ds = data_dir_load(nyx_no_particles)
    assert_equal(sorted(ds.field_list, fields))

