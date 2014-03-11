"""
Data structures for Streaming, in-memory datasets



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import weakref
import numpy as np
import uuid
from itertools import chain, product

from yt.utilities.io_handler import io_registry
from yt.funcs import *
from yt.config import ytcfg
from yt.data_objects.data_containers import \
    YTFieldData, \
    YTDataContainer, \
    YTSelectionContainer
from yt.data_objects.particle_unions import \
    ParticleUnion
from yt.data_objects.grid_patch import \
    AMRGridPatch
from yt.geometry.geometry_handler import \
    YTDataChunk
from yt.geometry.grid_geometry_handler import \
    GridGeometryHandler
from yt.data_objects.octree_subset import \
    OctreeSubset
from yt.geometry.oct_geometry_handler import \
    OctreeGeometryHandler
from yt.geometry.particle_geometry_handler import \
    ParticleGeometryHandler
from yt.fields.particle_fields import \
    particle_vector_functions, \
    particle_deposition_functions, \
    standard_particle_fields
from yt.geometry.oct_container import \
    OctreeContainer
from yt.geometry.unstructured_mesh_handler import \
           UnstructuredGeometryHandler
from yt.data_objects.static_output import \
    StaticOutput
from yt.utilities.logger import ytLogger as mylog
from yt.data_objects.field_info_container import \
    FieldInfoContainer, NullFunc
from yt.utilities.lib import \
    get_box_grids_level
from yt.utilities.decompose import \
    decompose_array, get_psize
from yt.utilities.definitions import \
    mpc_conversion, sec_conversion
from yt.utilities.flagging_methods import \
    FlaggingGrid
from yt.frontends.sph.data_structures import \
    ParticleFile
from yt.data_objects.unstructured_mesh import \
           SemiStructuredMesh

from .fields import \
    StreamFieldInfo, \
    add_stream_field, \
    KnownStreamFields, \
    _setup_particle_fields

class StreamGrid(AMRGridPatch):
    """
    Class representing a single In-memory Grid instance.
    """

    __slots__ = ['proc_num']
    _id_offset = 0
    def __init__(self, id, hierarchy):
        """
        Returns an instance of StreamGrid with *id*, associated with *filename*
        and *hierarchy*.
        """
        #All of the field parameters will be passed to us as needed.
        AMRGridPatch.__init__(self, id, filename = None, hierarchy = hierarchy)
        self._children_ids = []
        self._parent_id = -1
        self.Level = -1

    def _guess_properties_from_parent(self):
        rf = self.pf.refine_by
        my_ind = self.id - self._id_offset
        le = self.LeftEdge
        self.dds = self.Parent.dds/rf
        ParentLeftIndex = np.rint((self.LeftEdge-self.Parent.LeftEdge)/self.Parent.dds)
        self.start_index = rf*(ParentLeftIndex + self.Parent.get_global_startindex()).astype('int64')
        self.LeftEdge = self.Parent.LeftEdge + self.Parent.dds * ParentLeftIndex
        self.RightEdge = self.LeftEdge + self.ActiveDimensions*self.dds
        self.hierarchy.grid_left_edge[my_ind,:] = self.LeftEdge
        self.hierarchy.grid_right_edge[my_ind,:] = self.RightEdge
        self._child_mask = None
        self._child_index_mask = None
        self._child_indices = None
        self._setup_dx()

    def set_filename(self, filename):
        pass

    def __repr__(self):
        return "StreamGrid_%04i" % (self.id)

    @property
    def Parent(self):
        if self._parent_id == -1: return None
        return self.hierarchy.grids[self._parent_id - self._id_offset]

    @property
    def Children(self):
        return [self.hierarchy.grids[cid - self._id_offset]
                for cid in self._children_ids]

class StreamHandler(object):
    def __init__(self, left_edges, right_edges, dimensions,
                 levels, parent_ids, particle_count, processor_ids,
                 fields, io = None, particle_types = None, 
                 periodicity = (True, True, True)):
        if particle_types is None: particle_types = {}
        self.left_edges = left_edges
        self.right_edges = right_edges
        self.dimensions = dimensions
        self.levels = levels
        self.parent_ids = parent_ids
        self.particle_count = particle_count
        self.processor_ids = processor_ids
        self.num_grids = self.levels.size
        self.fields = fields
        self.io = io
        self.particle_types = particle_types
        self.periodicity = periodicity
            
    def get_fields(self):
        return self.fields.all_fields

    def get_particle_type(self, field) :

        if self.particle_types.has_key(field) :
            return self.particle_types[field]
        else :
            return False
        
class StreamHierarchy(GridGeometryHandler):

    grid = StreamGrid

    def __init__(self, pf, data_style = None):
        self.data_style = data_style
        self.float_type = 'float64'
        self.parameter_file = weakref.proxy(pf) # for _obtain_enzo
        self.stream_handler = pf.stream_handler
        self.float_type = "float64"
        self.directory = os.getcwd()
        GridGeometryHandler.__init__(self, pf, data_style)

    def _count_grids(self):
        self.num_grids = self.stream_handler.num_grids

    def _parse_hierarchy(self):
        self.grid_dimensions = self.stream_handler.dimensions
        self.grid_left_edge[:] = self.stream_handler.left_edges
        self.grid_right_edge[:] = self.stream_handler.right_edges
        self.grid_levels[:] = self.stream_handler.levels
        self.grid_procs = self.stream_handler.processor_ids
        self.grid_particle_count[:] = self.stream_handler.particle_count
        mylog.debug("Copying reverse tree")
        self.grids = []
        # We enumerate, so it's 0-indexed id and 1-indexed pid
        for id in xrange(self.num_grids):
            self.grids.append(self.grid(id, self))
            self.grids[id].Level = self.grid_levels[id, 0]
        parent_ids = self.stream_handler.parent_ids
        if parent_ids is not None:
            reverse_tree = self.stream_handler.parent_ids.tolist()
            # Initial setup:
            for gid,pid in enumerate(reverse_tree):
                if pid >= 0:
                    self.grids[id]._parent_id = pid
                    self.grids[pid]._children_ids.append(self.grids[gid].id)
        else:
            mylog.debug("Reconstructing parent-child relationships")
            self._reconstruct_parent_child()
        self.max_level = self.grid_levels.max()
        mylog.debug("Preparing grids")
        temp_grids = np.empty(self.num_grids, dtype='object')
        for i, grid in enumerate(self.grids):
            if (i%1e4) == 0: mylog.debug("Prepared % 7i / % 7i grids", i, self.num_grids)
            grid.filename = None
            grid._prepare_grid()
            grid.proc_num = self.grid_procs[i]
            temp_grids[i] = grid
        self.grids = temp_grids
        mylog.debug("Prepared")

    def _reconstruct_parent_child(self):
        mask = np.empty(len(self.grids), dtype='int32')
        mylog.debug("First pass; identifying child grids")
        for i, grid in enumerate(self.grids):
            get_box_grids_level(self.grid_left_edge[i,:],
                                self.grid_right_edge[i,:],
                                self.grid_levels[i] + 1,
                                self.grid_left_edge, self.grid_right_edge,
                                self.grid_levels, mask)
            ids = np.where(mask.astype("bool"))
            grid._children_ids = ids[0] # where is a tuple
        mylog.debug("Second pass; identifying parents")
        for i, grid in enumerate(self.grids): # Second pass
            for child in grid.Children:
                child._parent_id = i

    def _initialize_grid_arrays(self):
        GridGeometryHandler._initialize_grid_arrays(self)
        self.grid_procs = np.zeros((self.num_grids,1),'int32')

    def _setup_classes(self):
        dd = self._get_data_reader_dict()
        GridGeometryHandler._setup_classes(self, dd)

    def _detect_fields(self):
        # NOTE: Because particle unions add to the actual field list, without
        # having the keys in the field list itself, we need to double check
        # here.
        fl = set(self.stream_handler.get_fields())
        fl.update(set(getattr(self, "field_list", [])))
        self.field_list = list(fl)

    def _populate_grid_objects(self):
        for g in self.grids:
            g._setup_dx()
        self.max_level = self.grid_levels.max()

    def _setup_data_io(self):
        if self.stream_handler.io is not None:
            self.io = self.stream_handler.io
        else:
            self.io = io_registry[self.data_style](self.pf)

    def update_data(self, data) :

        """
        Update the stream data with a new data dict. If fields already exist,
        they will be replaced, but if they do not, they will be added. Fields
        already in the stream but not part of the data dict will be left
        alone. 
        """
        [update_field_names(d) for d in data]
        particle_types = set_particle_types(data[0])
        ftype = "io"

        for key in data[0].keys() :
            if key is "number_of_particles": continue
            self.stream_handler.particle_types[key] = particle_types[key]

        for i, grid in enumerate(self.grids) :
            if data[i].has_key("number_of_particles") :
                grid.NumberOfParticles = data[i].pop("number_of_particles")
            for fname in data[i]:
                if fname in grid.field_data:
                    grid.field_data.pop(fname, None)
                elif (ftype, fname) in grid.field_data:
                    grid.field_data.pop( ("io", fname) )
                self.stream_handler.fields[grid.id][fname] = data[i][fname]
            

        # We only want to create a superset of fields here.
        self._detect_fields()
        mylog.debug("Creating Particle Union 'all'")
        pu = ParticleUnion("all", list(self.pf.particle_types_raw))
        self.pf.add_particle_union(pu)
        self.pf.particle_types = tuple(set(self.pf.particle_types))
        self._setup_unknown_fields()
                
class StreamStaticOutput(StaticOutput):
    _hierarchy_class = StreamHierarchy
    _fieldinfo_fallback = StreamFieldInfo
    _fieldinfo_known = KnownStreamFields
    _data_style = 'stream'

    def __init__(self, stream_handler, storage_filename = None):
        #if parameter_override is None: parameter_override = {}
        #self._parameter_override = parameter_override
        #if conversion_override is None: conversion_override = {}
        #self._conversion_override = conversion_override

        self.stream_handler = stream_handler
        name = "InMemoryParameterFile_%s" % (uuid.uuid4().hex)
        from yt.data_objects.static_output import _cached_pfs
        _cached_pfs[name] = self
        StaticOutput.__init__(self, name, self._data_style)

        self.units = {}
        self.time_units = {}

    def _parse_parameter_file(self):
        self.basename = self.stream_handler.name
        self.parameters['CurrentTimeIdentifier'] = time.time()
        self.unique_identifier = self.parameters["CurrentTimeIdentifier"]
        self.domain_left_edge = self.stream_handler.domain_left_edge[:]
        self.domain_right_edge = self.stream_handler.domain_right_edge[:]
        self.refine_by = self.stream_handler.refine_by
        self.dimensionality = self.stream_handler.dimensionality
        self.periodicity = self.stream_handler.periodicity
        self.domain_dimensions = self.stream_handler.domain_dimensions
        self.current_time = self.stream_handler.simulation_time
        self.parameters['Gamma'] = 5/3
        self.parameters['EOSType'] = -1
        if self.stream_handler.cosmology_simulation:
            self.cosmological_simulation = 1
            self.current_redshift = self.stream_handler.current_redshift
            self.omega_lambda = self.stream_handler.omega_lambda
            self.omega_matter = self.stream_handler.omega_matter
            self.hubble_constant = self.stream_handler.hubble_constant
        else:
            self.current_redshift = self.omega_lambda = self.omega_matter = \
                self.hubble_constant = self.cosmological_simulation = 0.0

    def _set_units(self):
        pass

    @classmethod
    def _is_valid(cls, *args, **kwargs):
        return False

    @property
    def _skip_cache(self):
        return True

    def _setup_particle_type(self, ptype):
        orig = set(self.field_info.items())
        _setup_particle_fields(self.field_info, ptype)
        return [n for n, v in set(self.field_info.items()).difference(orig)]

class StreamDictFieldHandler(dict):
    _additional_fields = ()

    @property
    def all_fields(self): 
        fields = list(self._additional_fields) + self[0].keys()
        fields = list(set(fields))
        return fields

def update_field_names(data):
    orig_names = data.keys()
    for k in orig_names:
        if isinstance(k, tuple): continue
        s = getattr(data[k], "shape", ())
        if len(s) == 1:
            field = ("io", k)
        elif len(s) == 3:
            field = ("gas", k)
        elif len(s) == 0:
            continue
        else:
            raise NotImplementedError
        data[field] = data.pop(k)

def set_particle_types(data) :

    particle_types = {}
    
    for key in data.keys() :

        if key is "number_of_particles": continue
        
        if len(data[key].shape) == 1:
            particle_types[key] = True
        else :
            particle_types[key] = False
    
    return particle_types

def assign_particle_data(pf, pdata) :

    """
    Assign particle data to the grids using find_points. This
    will overwrite any existing particle data, so be careful!
    """
    
    if pf.h.num_grids > 1 :

        try:
            x, y, z = (pdata["io","particle_position_%s" % ax] for ax in 'xyz')
        except KeyError:
            raise KeyError("Cannot decompose particle data without position fields!")
        
        particle_grids, particle_grid_inds = pf.h.find_points(x,y,z)
        idxs = np.argsort(particle_grid_inds)
        particle_grid_count = np.bincount(particle_grid_inds,
                                          minlength=pf.h.num_grids)
        particle_indices = np.zeros(pf.h.num_grids + 1, dtype='int64')
        if pf.h.num_grids > 1 :
            np.add.accumulate(particle_grid_count.squeeze(),
                              out=particle_indices[1:])
        else :
            particle_indices[1] = particle_grid_count.squeeze()
    
        pdata.pop("number_of_particles")    
        grid_pdata = []
        
        for i, pcount in enumerate(particle_grid_count) :
            grid = {}
            grid["number_of_particles"] = pcount
            start = particle_indices[i]
            end = particle_indices[i+1]
            for key in pdata.keys() :
                grid[key] = pdata[key][idxs][start:end]
            grid_pdata.append(grid)

    else :

        grid_pdata = [pdata]
        
    pf.h.update_data(grid_pdata)
                                        
def load_uniform_grid(data, domain_dimensions, sim_unit_to_cm, bbox=None,
                      nprocs=1, sim_time=0.0, periodicity=(True, True, True)):
    r"""Load a uniform grid of data into yt as a
    :class:`~yt.frontends.stream.data_structures.StreamHandler`.

    This should allow a uniform grid of data to be loaded directly into yt and
    analyzed as would any others.  This comes with several caveats:
        * Units will be incorrect unless the data has already been converted to
          cgs.
        * Some functions may behave oddly, and parallelism will be
          disappointing or non-existent in most cases.
        * Particles may be difficult to integrate.

    Particle fields are detected as one-dimensional fields. The number of particles
    is set by the "number_of_particles" key in data.
    
    Parameters
    ----------
    data : dict
        This is a dict of numpy arrays, where the keys are the field names.
    domain_dimensions : array_like
        This is the domain dimensions of the grid
    sim_unit_to_cm : float
        Conversion factor from simulation units to centimeters
    bbox : array_like (xdim:zdim, LE:RE), optional
        Size of computational domain in units sim_unit_to_cm
    nprocs: integer, optional
        If greater than 1, will create this number of subarrays out of data
    sim_time : float, optional
        The simulation time in seconds
    periodicity : tuple of booleans
        Determines whether the data will be treated as periodic along
        each axis

    Examples
    --------

    >>> arr = np.random.random((128, 128, 129))
    >>> data = dict(Density = arr)
    >>> bbox = np.array([[0., 1.0], [-1.5, 1.5], [1.0, 2.5]])
    >>> pf = load_uniform_grid(data, arr.shape, 3.08e24, bbox=bbox, nprocs=12)

    """

    domain_dimensions = np.array(domain_dimensions)
    if bbox is None:
        bbox = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], 'float64')
    domain_left_edge = np.array(bbox[:, 0], 'float64')
    domain_right_edge = np.array(bbox[:, 1], 'float64')
    grid_levels = np.zeros(nprocs, dtype='int32').reshape((nprocs,1))

    sfh = StreamDictFieldHandler()
    
    if data.has_key("number_of_particles") :
        number_of_particles = data.pop("number_of_particles")
    else :
        number_of_particles = int(0)
    
    if number_of_particles > 0 :
        particle_types = set_particle_types(data)
        pdata = {}
        pdata["number_of_particles"] = number_of_particles
        for key in data.keys() :
            if len(data[key].shape) == 1 :
                if not isinstance(key, tuple):
                    field = ("io", key)
                    mylog.debug("Reassigning '%s' to '%s'", key, field)
                else:
                    field = key
                sfh._additional_fields += (field,)
                pdata[field] = data.pop(key)
    else :
        particle_types = {}
    update_field_names(data)
    
    if nprocs > 1:
        temp = {}
        new_data = {}
        for key in data.keys():
            psize = get_psize(np.array(data[key].shape), nprocs)
            grid_left_edges, grid_right_edges, temp[key] = \
                             decompose_array(data[key], psize, bbox)
            grid_dimensions = np.array([grid.shape for grid in temp[key]],
                                       dtype="int32")
        for gid in range(nprocs):
            new_data[gid] = {}
            for key in temp.keys():
                new_data[gid].update({key:temp[key][gid]})
        sfh.update(new_data)
        del new_data, temp
    else:
        sfh.update({0:data})
        grid_left_edges = domain_left_edge
        grid_right_edges = domain_right_edge
        grid_dimensions = domain_dimensions.reshape(nprocs,3).astype("int32")

    handler = StreamHandler(
        grid_left_edges,
        grid_right_edges,
        grid_dimensions,
        grid_levels,
        -np.ones(nprocs, dtype='int64'),
        np.zeros(nprocs, dtype='int64').reshape(nprocs,1), # Temporary
        np.zeros(nprocs).reshape((nprocs,1)),
        sfh,
        particle_types=particle_types,
        periodicity=periodicity
    )

    handler.name = "UniformGridData"
    handler.domain_left_edge = domain_left_edge
    handler.domain_right_edge = domain_right_edge
    handler.refine_by = 2
    handler.dimensionality = 3
    handler.domain_dimensions = domain_dimensions
    handler.simulation_time = sim_time
    handler.cosmology_simulation = 0

    spf = StreamStaticOutput(handler)
    spf.units["cm"] = sim_unit_to_cm
    spf.units['1'] = 1.0
    spf.units["unitary"] = 1.0
    box_in_mpc = sim_unit_to_cm / mpc_conversion['cm']
    for unit in mpc_conversion.keys():
        spf.units[unit] = mpc_conversion[unit] * box_in_mpc

    # Now figure out where the particles go

    if number_of_particles > 0 :
        if ("io", "particle_position_x") not in pdata:
            pdata_ftype = {}
            for f in [k for k in sorted(pdata)]:
                if not hasattr(pdata[f], "shape"): continue
                pdata_ftype["io",f] = pdata.pop(f)
            pdata_ftype.update(pdata)
            pdata = pdata_ftype
        assign_particle_data(spf, pdata)
    
    return spf

def load_amr_grids(grid_data, domain_dimensions, sim_unit_to_cm, bbox=None,
                   sim_time=0.0):
    r"""Load a set of grids of data into yt as a
    :class:`~yt.frontends.stream.data_structures.StreamHandler`.

    This should allow a sequence of grids of varying resolution of data to be
    loaded directly into yt and analyzed as would any others.  This comes with
    several caveats:
        * Units will be incorrect unless the data has already been converted to
          cgs.
        * Some functions may behave oddly, and parallelism will be
          disappointing or non-existent in most cases.
        * Particles may be difficult to integrate.
        * No consistency checks are performed on the hierarchy

    Parameters
    ----------
    grid_data : list of dicts
        This is a list of dicts.  Each dict must have entries "left_edge",
        "right_edge", "dimensions", "level", and then any remaining entries are
        assumed to be fields.  They also may include a particle count, otherwise
        assumed to be zero. This will be modified in place and can't be
        assumed to be static.
    domain_dimensions : array_like
        This is the domain dimensions of the grid
    sim_unit_to_cm : float
        Conversion factor from simulation units to centimeters
    bbox : array_like (xdim:zdim, LE:RE), optional
        Size of computational domain in units sim_unit_to_cm
    sim_time : float, optional
        The simulation time in seconds

    Examples
    --------

    >>> grid_data = [
    ...     dict(left_edge = [0.0, 0.0, 0.0],
    ...          right_edge = [1.0, 1.0, 1.],
    ...          level = 0,
    ...          dimensions = [32, 32, 32],
    ...          number_of_particles = 0)
    ...     dict(left_edge = [0.25, 0.25, 0.25],
    ...          right_edge = [0.75, 0.75, 0.75],
    ...          level = 1,
    ...          dimensions = [32, 32, 32],
    ...          number_of_particles = 0)
    ... ]
    ... 
    >>> for g in grid_data:
    ...     g["Density"] = np.random.random(g["dimensions"]) * 2**g["level"]
    ...
    >>> pf = load_amr_grids(grid_data, [32, 32, 32], 1.0)
    """

    domain_dimensions = np.array(domain_dimensions)
    ngrids = len(grid_data)
    if bbox is None:
        bbox = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], 'float64')
    domain_left_edge = np.array(bbox[:, 0], 'float64')
    domain_right_edge = np.array(bbox[:, 1], 'float64')
    grid_levels = np.zeros((ngrids, 1), dtype='int32')
    grid_left_edges = np.zeros((ngrids, 3), dtype="float32")
    grid_right_edges = np.zeros((ngrids, 3), dtype="float32")
    grid_dimensions = np.zeros((ngrids, 3), dtype="int32")
    number_of_particles = np.zeros((ngrids,1), dtype='int64')
    sfh = StreamDictFieldHandler()
    for i, g in enumerate(grid_data):
        grid_left_edges[i,:] = g.pop("left_edge")
        grid_right_edges[i,:] = g.pop("right_edge")
        grid_dimensions[i,:] = g.pop("dimensions")
        grid_levels[i,:] = g.pop("level")
        if g.has_key("number_of_particles") :
            number_of_particles[i,:] = g.pop("number_of_particles")  
        update_field_names(g)
        sfh[i] = g
            
    handler = StreamHandler(
        grid_left_edges,
        grid_right_edges,
        grid_dimensions,
        grid_levels,
        None, # parent_ids is none
        number_of_particles,
        np.zeros(ngrids).reshape((ngrids,1)),
        sfh,
        particle_types=set_particle_types(grid_data[0])
    )

    handler.name = "AMRGridData"
    handler.domain_left_edge = domain_left_edge
    handler.domain_right_edge = domain_right_edge
    handler.refine_by = 2
    handler.dimensionality = 3
    handler.domain_dimensions = domain_dimensions
    handler.simulation_time = sim_time
    handler.cosmology_simulation = 0

    spf = StreamStaticOutput(handler)
    spf.units["cm"] = sim_unit_to_cm
    spf.units['1'] = 1.0
    spf.units["unitary"] = 1.0
    box_in_mpc = sim_unit_to_cm / mpc_conversion['cm']
    for unit in mpc_conversion.keys():
        spf.units[unit] = mpc_conversion[unit] * box_in_mpc
    return spf

def refine_amr(base_pf, refinement_criteria, fluid_operators, max_level,
               callback = None):
    r"""Given a base parameter file, repeatedly apply refinement criteria and
    fluid operators until a maximum level is reached.

    Parameters
    ----------
    base_pf : StaticOutput
        This is any static output.  It can also be a stream static output, for
        instance as returned by load_uniform_data.
    refinement_critera : list of :class:`~yt.utilities.flagging_methods.FlaggingMethod`
        These criteria will be applied in sequence to identify cells that need
        to be refined.
    fluid_operators : list of :class:`~yt.utilities.initial_conditions.FluidOperator`
        These fluid operators will be applied in sequence to all resulting
        grids.
    max_level : int
        The maximum level to which the data will be refined
    callback : function, optional
        A function that will be called at the beginning of each refinement
        cycle, with the current parameter file.

    Examples
    --------
    >>> domain_dims = (32, 32, 32)
    >>> data = np.zeros(domain_dims) + 0.25
    >>> fo = [ic.CoredSphere(0.05, 0.3, [0.7,0.4,0.75], {"Density": (0.25, 100.0)})]
    >>> rc = [fm.flagging_method_registry["overdensity"](8.0)]
    >>> ug = load_uniform_grid({'Density': data}, domain_dims, 1.0)
    >>> pf = refine_amr(ug, rc, fo, 5)
    """

    # If we have particle data, set it aside for now

    number_of_particles = np.sum([grid.NumberOfParticles
                                  for grid in base_pf.h.grids])

    if number_of_particles > 0 :
        pdata = {}
        for field in base_pf.h.field_list :
            if not isinstance(field, tuple):
                field = ("unknown", field)
            fi = base_pf._get_field_info(*field)
            if fi.particle_type :
                pdata[field] = np.concatenate([grid[field]
                                               for grid in base_pf.h.grids])
        pdata["number_of_particles"] = number_of_particles
        
    last_gc = base_pf.h.num_grids
    cur_gc = -1
    pf = base_pf    
    bbox = np.array( [ (pf.domain_left_edge[i], pf.domain_right_edge[i])
                       for i in range(3) ])
    while pf.h.max_level < max_level and last_gc != cur_gc:
        mylog.info("Refining another level.  Current max level: %s",
                  pf.h.max_level)
        last_gc = pf.h.grids.size
        for m in fluid_operators: m.apply(pf)
        if callback is not None: callback(pf)
        grid_data = []
        for g in pf.h.grids:
            gd = dict( left_edge = g.LeftEdge,
                       right_edge = g.RightEdge,
                       level = g.Level,
                       dimensions = g.ActiveDimensions )
            for field in pf.h.field_list:
                if not isinstance(field, tuple):
                    field = ("unknown", field)
                fi = pf._get_field_info(*field)
                if not fi.particle_type :
                    gd[field] = g[field]
            grid_data.append(gd)
            if g.Level < pf.h.max_level: continue
            fg = FlaggingGrid(g, refinement_criteria)
            nsg = fg.find_subgrids()
            for sg in nsg:
                LE = sg.left_index * g.dds + pf.domain_left_edge
                dims = sg.dimensions * pf.refine_by
                grid = pf.h.smoothed_covering_grid(g.Level + 1, LE, dims)
                gd = dict(left_edge = LE, right_edge = grid.right_edge,
                          level = g.Level + 1, dimensions = dims)
                for field in pf.h.field_list:
                    if not isinstance(field, tuple):
                        field = ("unknown", field)
                    fi = pf._get_field_info(*field)
                    if not fi.particle_type :
                        gd[field] = grid[field]
                grid_data.append(gd)
        
        pf = load_amr_grids(grid_data, pf.domain_dimensions, 1.0,
                            bbox = bbox)
        cur_gc = pf.h.num_grids

    # Now reassign particle data to grids

    if number_of_particles > 0:
        if ("io", "particle_position_x") not in pdata:
            pdata_ftype = {}
            for f in [k for k in sorted(pdata)]:
                if not hasattr(pdata[f], "shape"): continue
                mylog.debug("Reassigning '%s' to ('io','%s')", f, f)
                pdata_ftype["io",f] = pdata.pop(f)
            pdata_ftype.update(pdata)
            pdata = pdata_ftype
        assign_particle_data(pf, pdata)
    
    return pf

class StreamParticleGeometryHandler(ParticleGeometryHandler):

    
    def __init__(self, pf, data_style = None):
        self.stream_handler = pf.stream_handler
        super(StreamParticleGeometryHandler, self).__init__(pf, data_style)

    def _setup_data_io(self):
        if self.stream_handler.io is not None:
            self.io = self.stream_handler.io
        else:
            self.io = io_registry[self.data_style](self.pf)

class StreamParticleFile(ParticleFile):
    pass

class StreamParticlesStaticOutput(StreamStaticOutput):
    _hierarchy_class = StreamParticleGeometryHandler
    _file_class = StreamParticleFile
    _fieldinfo_fallback = StreamFieldInfo
    _fieldinfo_known = KnownStreamFields
    _data_style = "stream_particles"
    file_count = 1
    filename_template = "stream_file"
    n_ref = 64
    over_refine_factor = 1

def load_particles(data, sim_unit_to_cm, bbox=None,
                      sim_time=0.0, periodicity=(True, True, True),
                      n_ref = 64, over_refine_factor = 1):
    r"""Load a set of particles into yt as a
    :class:`~yt.frontends.stream.data_structures.StreamParticleHandler`.

    This should allow a collection of particle data to be loaded directly into
    yt and analyzed as would any others.  This comes with several caveats:
        * Units will be incorrect unless the data has already been converted to
          cgs.
        * Some functions may behave oddly, and parallelism will be
          disappointing or non-existent in most cases.

    This will initialize an Octree of data.  Note that fluid fields will not
    work yet, or possibly ever.
    
    Parameters
    ----------
    data : dict
        This is a dict of numpy arrays, where the keys are the field names.
        Particles positions must be named "particle_position_x",
        "particle_position_y", "particle_position_z".
    sim_unit_to_cm : float
        Conversion factor from simulation units to centimeters
    bbox : array_like (xdim:zdim, LE:RE), optional
        Size of computational domain in units sim_unit_to_cm
    sim_time : float, optional
        The simulation time in seconds
    periodicity : tuple of booleans
        Determines whether the data will be treated as periodic along
        each axis
    n_ref : int
        The number of particles that result in refining an oct used for
        indexing the particles.

    Examples
    --------

    >>> pos = [np.random.random(128*128*128) for i in range(3)]
    >>> data = dict(particle_position_x = pos[0],
    ...             particle_position_y = pos[1],
    ...             particle_position_z = pos[2])
    >>> bbox = np.array([[0., 1.0], [0.0, 1.0], [0.0, 1.0]])
    >>> pf = load_particles(data, 3.08e24, bbox=bbox)

    """

    domain_dimensions = np.ones(3, "int32") * 2
    nprocs = 1
    if bbox is None:
        bbox = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], 'float64')
    domain_left_edge = np.array(bbox[:, 0], 'float64')
    domain_right_edge = np.array(bbox[:, 1], 'float64')
    grid_levels = np.zeros(nprocs, dtype='int32').reshape((nprocs,1))

    sfh = StreamDictFieldHandler()
    
    pdata = {}
    for key in data.keys() :
        if not isinstance(key, tuple):
            field = ("io", key)
            mylog.debug("Reassigning '%s' to '%s'", key, field)
        else:
            field = key
        pdata[field] = data[key]
        sfh._additional_fields += (field,)
    data = pdata # Drop reference count
    update_field_names(data)
    particle_types = set_particle_types(data)

    sfh.update({'stream_file':data})
    grid_left_edges = domain_left_edge
    grid_right_edges = domain_right_edge
    grid_dimensions = domain_dimensions.reshape(nprocs,3).astype("int32")

    # I'm not sure we need any of this.
    handler = StreamHandler(
        grid_left_edges,
        grid_right_edges,
        grid_dimensions,
        grid_levels,
        -np.ones(nprocs, dtype='int64'),
        np.zeros(nprocs, dtype='int64').reshape(nprocs,1), # Temporary
        np.zeros(nprocs).reshape((nprocs,1)),
        sfh,
        particle_types=particle_types,
        periodicity=periodicity
    )

    handler.name = "ParticleData"
    handler.domain_left_edge = domain_left_edge
    handler.domain_right_edge = domain_right_edge
    handler.refine_by = 2
    handler.dimensionality = 3
    handler.domain_dimensions = domain_dimensions
    handler.simulation_time = sim_time
    handler.cosmology_simulation = 0

    spf = StreamParticlesStaticOutput(handler)
    spf.n_ref = n_ref
    spf.over_refine_factor = over_refine_factor
    spf.units["cm"] = sim_unit_to_cm
    spf.units['1'] = 1.0
    spf.units["unitary"] = 1.0
    box_in_mpc = sim_unit_to_cm / mpc_conversion['cm']
    for unit in mpc_conversion.keys():
        spf.units[unit] = mpc_conversion[unit] * box_in_mpc

    return spf

class StreamOctreeSubset(OctreeSubset):
    domain_id = 1
    _domain_offset = 1

    def __init__(self, base_region, pf, oct_handler, over_refine_factor = 1):
        self._num_zones = 1 << (over_refine_factor)
        self.field_data = YTFieldData()
        self.field_parameters = {}
        self.pf = pf
        self.hierarchy = self.pf.hierarchy
        self.oct_handler = oct_handler
        self._last_mask = None
        self._last_selector_id = None
        self._current_particle_type = 'io'
        self._current_fluid_type = self.pf.default_fluid_type
        self.base_region = base_region
        self.base_selector = base_region.selector

    def fill(self, content, dest, selector, offset):
        # Here we get a copy of the file, which we skip through and read the
        # bits we want.
        oct_handler = self.oct_handler
        cell_count = selector.count_oct_cells(self.oct_handler, self.domain_id)
        levels, cell_inds, file_inds = self.oct_handler.file_index_octs(
            selector, self.domain_id, cell_count)
        levels[:] = 0
        dest.update((field, np.empty(cell_count, dtype="float64"))
                    for field in content)
        # Make references ...
        count = oct_handler.fill_level(0, levels, cell_inds, file_inds, 
                                       dest, content, offset)
        return count

class StreamOctreeHandler(OctreeGeometryHandler):

    def __init__(self, pf, data_style = None):
        self.stream_handler = pf.stream_handler
        self.data_style = data_style
        super(StreamOctreeHandler, self).__init__(pf, data_style)

    def _setup_data_io(self):
        if self.stream_handler.io is not None:
            self.io = self.stream_handler.io
        else:
            self.io = io_registry[self.data_style](self.pf)

    def _initialize_oct_handler(self):
        header = dict(dims = [1, 1, 1],
                      left_edge = self.pf.domain_left_edge,
                      right_edge = self.pf.domain_right_edge,
                      octree = self.pf.octree_mask,
                      over_refine = self.pf.over_refine_factor,
                      partial_coverage = self.pf.partial_coverage)
        self.oct_handler = OctreeContainer.load_octree(header)

    def _identify_base_chunk(self, dobj):
        if getattr(dobj, "_chunk_info", None) is None:
            base_region = getattr(dobj, "base_region", dobj)
            subset = [StreamOctreeSubset(base_region, self.parameter_file,
                                         self.oct_handler,
                                         self.pf.over_refine_factor)]
            dobj._chunk_info = subset
        dobj._current_chunk = list(self._chunk_all(dobj))[0]

    def _chunk_all(self, dobj):
        oobjs = getattr(dobj._current_chunk, "objs", dobj._chunk_info)
        yield YTDataChunk(dobj, "all", oobjs, None)

    def _chunk_spatial(self, dobj, ngz, sort = None, preload_fields = None):
        sobjs = getattr(dobj._current_chunk, "objs", dobj._chunk_info)
        # We actually do not really use the data files except as input to the
        # ParticleOctreeSubset.
        # This is where we will perform cutting of the Octree and
        # load-balancing.  That may require a specialized selector object to
        # cut based on some space-filling curve index.
        for i,og in enumerate(sobjs):
            if ngz > 0:
                g = og.retrieve_ghost_zones(ngz, [], smoothed=True)
            else:
                g = og
            yield YTDataChunk(dobj, "spatial", [g])

    def _chunk_io(self, dobj, cache = True):
        oobjs = getattr(dobj._current_chunk, "objs", dobj._chunk_info)
        for subset in oobjs:
            yield YTDataChunk(dobj, "io", [subset], None, cache = cache)

    def _setup_classes(self):
        dd = self._get_data_reader_dict()
        super(StreamOctreeHandler, self)._setup_classes(dd)

    def _detect_fields(self):
        # NOTE: Because particle unions add to the actual field list, without
        # having the keys in the field list itself, we need to double check
        # here.
        fl = set(self.stream_handler.get_fields())
        fl.update(set(getattr(self, "field_list", [])))
        self.field_list = list(fl)


class StreamOctreeStaticOutput(StreamStaticOutput):
    _hierarchy_class = StreamOctreeHandler
    _fieldinfo_fallback = StreamFieldInfo
    _fieldinfo_known = KnownStreamFields
    _data_style = "stream_octree"

def load_octree(octree_mask, data, sim_unit_to_cm,
                bbox=None, sim_time=0.0, periodicity=(True, True, True),
                over_refine_factor = 1, partial_coverage = 1):
    r"""Load an octree mask into yt.

    Octrees can be saved out by calling save_octree on an OctreeContainer.
    This enables them to be loaded back in.

    This will initialize an Octree of data.  Note that fluid fields will not
    work yet, or possibly ever.
    
    Parameters
    ----------
    octree_mask : np.ndarray[uint8_t]
        This is a depth-first refinement mask for an Octree.  It should be of
        size n_octs * 8, where each item is 1 for an oct-cell being refined and
        0 for it not being refined.  Note that for over_refine_factors != 1,
        the children count will still be 8, so this is always 8.
    data : dict
        A dictionary of 1D arrays.  Note that these must of the size of the
        number of "False" values in the ``octree_mask``.
    sim_unit_to_cm : float
        Conversion factor from simulation units to centimeters
    bbox : array_like (xdim:zdim, LE:RE), optional
        Size of computational domain in units sim_unit_to_cm
    sim_time : float, optional
        The simulation time in seconds
    periodicity : tuple of booleans
        Determines whether the data will be treated as periodic along
        each axis
    partial_coverage : boolean
        Whether or not an oct can be refined cell-by-cell, or whether all 8 get
        refined.

    """

    nz = (1 << (over_refine_factor))
    domain_dimensions = np.array([nz, nz, nz])
    nprocs = 1
    if bbox is None:
        bbox = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], 'float64')
    domain_left_edge = np.array(bbox[:, 0], 'float64')
    domain_right_edge = np.array(bbox[:, 1], 'float64')
    grid_levels = np.zeros(nprocs, dtype='int32').reshape((nprocs,1))
    update_field_names(data)

    sfh = StreamDictFieldHandler()
    
    particle_types = set_particle_types(data)
    
    sfh.update({0:data})
    grid_left_edges = domain_left_edge
    grid_right_edges = domain_right_edge
    grid_dimensions = domain_dimensions.reshape(nprocs,3).astype("int32")

    # I'm not sure we need any of this.
    handler = StreamHandler(
        grid_left_edges,
        grid_right_edges,
        grid_dimensions,
        grid_levels,
        -np.ones(nprocs, dtype='int64'),
        np.zeros(nprocs, dtype='int64').reshape(nprocs,1), # Temporary
        np.zeros(nprocs).reshape((nprocs,1)),
        sfh,
        particle_types=particle_types,
        periodicity=periodicity
    )

    handler.name = "OctreeData"
    handler.domain_left_edge = domain_left_edge
    handler.domain_right_edge = domain_right_edge
    handler.refine_by = 2
    handler.dimensionality = 3
    handler.domain_dimensions = domain_dimensions
    handler.simulation_time = sim_time
    handler.cosmology_simulation = 0

    spf = StreamOctreeStaticOutput(handler)
    spf.octree_mask = octree_mask
    spf.partial_coverage = partial_coverage
    spf.units["cm"] = sim_unit_to_cm
    spf.units['1'] = 1.0
    spf.units["unitary"] = 1.0
    box_in_mpc = sim_unit_to_cm / mpc_conversion['cm']
    spf.over_refine_factor = over_refine_factor
    for unit in mpc_conversion.keys():
        spf.units[unit] = mpc_conversion[unit] * box_in_mpc

    return spf

_cis = np.fromiter(chain.from_iterable(product([0,1], [0,1], [0,1])),
                dtype=np.int64, count = 8*3)
_cis.shape = (8, 3)

def hexahedral_connectivity(xgrid, ygrid, zgrid):
    nx = len(xgrid)
    ny = len(ygrid)
    nz = len(zgrid)
    coords = np.zeros((nx, ny, nz, 3), dtype="float64", order="C")
    coords[:,:,:,0] = xgrid[:,None,None]
    coords[:,:,:,1] = ygrid[None,:,None]
    coords[:,:,:,2] = zgrid[None,None,:]
    coords.shape = (nx * ny * nz, 3)
    cycle = np.rollaxis(np.indices((nx-1,ny-1,nz-1)), 0, 4)
    cycle.shape = ((nx-1)*(ny-1)*(nz-1), 3)
    off = _cis + cycle[:, np.newaxis]
    connectivity = ((off[:,:,0] * ny) + off[:,:,1]) * nz + off[:,:,2]
    return coords, connectivity

class StreamHexahedralMesh(SemiStructuredMesh):
    _connectivity_length = 8
    _index_offset = 0

class StreamHexahedralHierarchy(UnstructuredGeometryHandler):

    def __init__(self, pf, data_style = None):
        self.stream_handler = pf.stream_handler
        super(StreamHexahedralHierarchy, self).__init__(pf, data_style)

    def _initialize_mesh(self):
        coords = self.stream_handler.fields.pop('coordinates')
        connec = self.stream_handler.fields.pop('connectivity')
        self.meshes = [StreamHexahedralMesh(0,
          self.hierarchy_filename, connec, coords, self)]

    def _setup_data_io(self):
        if self.stream_handler.io is not None:
            self.io = self.stream_handler.io
        else:
            self.io = io_registry[self.data_style](self.pf)

    def _detect_fields(self):
        # NOTE: Because particle unions add to the actual field list, without
        # having the keys in the field list itself, we need to double check
        # here.
        fl = set(self.stream_handler.get_fields())
        fl.update(set(getattr(self, "field_list", [])))
        self.field_list = list(fl)


class StreamHexahedralStaticOutput(StreamStaticOutput):
    _hierarchy_class = StreamHexahedralHierarchy
    _fieldinfo_fallback = StreamFieldInfo
    _fieldinfo_known = KnownStreamFields
    _data_style = "stream_hexahedral"

def load_hexahedral_mesh(data, connectivity, coordinates,
                         sim_unit_to_cm, bbox=None,
                         sim_time=0.0, periodicity=(True, True, True)):
    r"""Load a hexahedral mesh of data into yt as a
    :class:`~yt.frontends.stream.data_structures.StreamHandler`.

    This should allow a semistructured grid of data to be loaded directly into
    yt and analyzed as would any others.  This comes with several caveats:
        * Units will be incorrect unless the data has already been converted to
          cgs.
        * Some functions may behave oddly, and parallelism will be
          disappointing or non-existent in most cases.
        * Particles may be difficult to integrate.

    Particle fields are detected as one-dimensional fields. The number of particles
    is set by the "number_of_particles" key in data.
    
    Parameters
    ----------
    data : dict
        This is a dict of numpy arrays, where the keys are the field names.
        There must only be one.
    connectivity : array_like
        This should be of size (N,8) where N is the number of zones.
    coordinates : array_like
        This should be of size (M,3) where M is the number of vertices
        indicated in the connectivity matrix.
    sim_unit_to_cm : float
        Conversion factor from simulation units to centimeters
    bbox : array_like (xdim:zdim, LE:RE), optional
        Size of computational domain in units sim_unit_to_cm
    sim_time : float, optional
        The simulation time in seconds
    periodicity : tuple of booleans
        Determines whether the data will be treated as periodic along
        each axis

    """

    domain_dimensions = np.ones(3, "int32") * 2
    nprocs = 1
    if bbox is None:
        bbox = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], 'float64')
    domain_left_edge = np.array(bbox[:, 0], 'float64')
    domain_right_edge = np.array(bbox[:, 1], 'float64')
    grid_levels = np.zeros(nprocs, dtype='int32').reshape((nprocs,1))

    sfh = StreamDictFieldHandler()
    
    particle_types = set_particle_types(data)
    
    sfh.update({'connectivity': connectivity,
                'coordinates': coordinates,
                0: data})
    grid_left_edges = domain_left_edge
    grid_right_edges = domain_right_edge
    grid_dimensions = domain_dimensions.reshape(nprocs,3).astype("int32")

    # I'm not sure we need any of this.
    handler = StreamHandler(
        grid_left_edges,
        grid_right_edges,
        grid_dimensions,
        grid_levels,
        -np.ones(nprocs, dtype='int64'),
        np.zeros(nprocs, dtype='int64').reshape(nprocs,1), # Temporary
        np.zeros(nprocs).reshape((nprocs,1)),
        sfh,
        particle_types=particle_types,
        periodicity=periodicity
    )

    handler.name = "HexahedralMeshData"
    handler.domain_left_edge = domain_left_edge
    handler.domain_right_edge = domain_right_edge
    handler.refine_by = 2
    handler.dimensionality = 3
    handler.domain_dimensions = domain_dimensions
    handler.simulation_time = sim_time
    handler.cosmology_simulation = 0

    spf = StreamHexahedralStaticOutput(handler)
    spf.units["cm"] = sim_unit_to_cm
    spf.units['1'] = 1.0
    spf.units["unitary"] = 1.0
    box_in_mpc = sim_unit_to_cm / mpc_conversion['cm']
    for unit in mpc_conversion.keys():
        spf.units[unit] = mpc_conversion[unit] * box_in_mpc

    return spf
