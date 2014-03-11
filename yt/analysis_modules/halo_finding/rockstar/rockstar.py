"""
Operations to get Rockstar loaded up



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from yt.mods import *
from yt.utilities.parallel_tools.parallel_analysis_interface import \
    ParallelAnalysisInterface, ProcessorPool, Communicator
from yt.analysis_modules.halo_finding.halo_objects import * #Halos & HaloLists
from yt.config import ytcfg
from yt.utilities.exceptions import YTRockstarMultiMassNotSupported

import rockstar_interface

import socket
import time
import threading
import signal
import os
from os import environ
from os import mkdir
from os import path

class InlineRunner(ParallelAnalysisInterface):
    def __init__(self):
        # If this is being run inline, num_readers == comm.size, always.
        psize = ytcfg.getint("yt", "__global_parallel_size")
        self.num_readers = psize
        # No choice for you, everyone's a writer too!
        self.num_writers =  psize
    
    def run(self, handler, pool):
        # If inline, we use forks.
        server_pid = 0
        # Start a server on only one machine/fork.
        if pool.comm.rank == 0:
            server_pid = os.fork()
            if server_pid == 0:
                handler.start_server()
                os._exit(0)
        # Start writers on all.
        writer_pid = 0
        time.sleep(0.05 + pool.comm.rank/10.0)
        writer_pid = os.fork()
        if writer_pid == 0:
            handler.start_writer()
            os._exit(0)
        # Everyone's a reader!
        time.sleep(0.05 + pool.comm.rank/10.0)
        handler.start_reader()
        # Make sure the forks are done, which they should be.
        if writer_pid != 0:
            os.waitpid(writer_pid, 0)
        if server_pid != 0:
            os.waitpid(server_pid, 0)

    def setup_pool(self):
        pool = ProcessorPool()
        # Everyone is a reader, and when we're inline, that's all that matters.
        readers = np.arange(ytcfg.getint("yt", "__global_parallel_size"))
        pool.add_workgroup(ranks=readers, name="readers")
        return pool, pool.workgroups[0]

class StandardRunner(ParallelAnalysisInterface):
    def __init__(self, num_readers, num_writers):
        self.num_readers = num_readers
        psize = ytcfg.getint("yt", "__global_parallel_size")
        if num_writers is None:
            self.num_writers =  psize - num_readers - 1
        else:
            self.num_writers = min(num_writers, psize)
        if self.num_readers + self.num_writers + 1 != psize:
            mylog.error('%i reader + %i writers != %i mpi',
                    self.num_readers, self.num_writers, psize)
            raise RuntimeError
    
    def run(self, handler, wg):
        # Not inline so we just launch them directly from our MPI threads.
        if wg.name == "server":
            handler.start_server()
        if wg.name == "readers":
            time.sleep(0.05)
            handler.start_reader()
        if wg.name == "writers":
            time.sleep(0.1)
            handler.start_writer()
    
    def setup_pool(self):
        pool = ProcessorPool()
        pool, workgroup = ProcessorPool.from_sizes(
           [ (1, "server"),
             (self.num_readers, "readers"),
             (self.num_writers, "writers") ]
        )
        return pool, workgroup

class RockstarHaloFinder(ParallelAnalysisInterface):
    r"""Spawns the Rockstar Halo finder, distributes dark matter
    particles and finds halos.

    The halo finder requires dark matter particles of a fixed size.
    Rockstar has three main processes: reader, writer, and the 
    server which coordinates reader/writer processes.

    Parameters
    ----------
    ts   : TimeSeriesData, StaticOutput
        This is the data source containing the DM particles. Because 
        halo IDs may change from one snapshot to the next, the only
        way to keep a consistent halo ID across time is to feed 
        Rockstar a set of snapshots, ie, via TimeSeriesData.
    num_readers: int
        The number of reader can be increased from the default
        of 1 in the event that a single snapshot is split among
        many files. This can help in cases where performance is
        IO-limited. Default is 1. If run inline, it is
        equal to the number of MPI threads.
    num_writers: int
        The number of writers determines the number of processing threads
        as well as the number of threads writing output data.
        The default is set to comm.size-num_readers-1. If run inline,
        the default is equal to the number of MPI threads.
    outbase: str
        This is where the out*list files that Rockstar makes should be
        placed. Default is 'rockstar_halos'.
    particle_type: str
        This is the "particle type" that can be found in the data.  This can be
        a filtered particle or an inherent type.
    force_res: float
        This parameter specifies the force resolution that Rockstar uses
        in units of Mpc/h.
        If no value is provided, this parameter is automatically set to
        the width of the smallest grid element in the simulation from the
        last data snapshot (i.e. the one where time has evolved the
        longest) in the time series:
        ``pf_last.h.get_smallest_dx() * pf_last['mpch']``.
    total_particles : int
        If supplied, this is a pre-calculated total number of particles present
        in the simulation. For example, this is useful when analyzing a series
        of snapshots where the number of dark matter particles should not
        change and this will save some disk access time. If left unspecified,
        it will be calculated automatically. Default: ``None``.
    particle_mass : float
        If supplied, use this as the particle mass supplied to rockstar.
        Otherwise, the smallest particle mass will be identified and calculated
        internally.  This is useful for multi-dm-mass simulations. Note that
        this will only give sensible results for halos that are not "polluted"
        by lower resolution particles. Default: ``None``.
        
    Returns
    -------
    None

    Examples
    --------
    To use the script below you must run it using MPI:
    mpirun -np 3 python test_rockstar.py --parallel

    test_rockstar.py:

    from yt.analysis_modules.halo_finding.rockstar.api import RockstarHaloFinder
    from yt.mods import *
    import sys

    ts = TimeSeriesData.from_filenames('/u/cmoody3/data/a*')
    pm = 7.81769027e+11
    rh = RockstarHaloFinder(ts)
    rh.run()
    """
    def __init__(self, ts, num_readers = 1, num_writers = None,
            outbase="rockstar_halos", particle_type="all",
            force_res=None, total_particles=None, dm_only=False,
            particle_mass=None):
        mylog.warning("The citation for the Rockstar halo finder can be found at")
        mylog.warning("http://adsabs.harvard.edu/abs/2013ApJ...762..109B")
        ParallelAnalysisInterface.__init__(self)
        # Decide how we're working.
        if ytcfg.getboolean("yt", "inline") == True:
            self.runner = InlineRunner()
        else:
            self.runner = StandardRunner(num_readers, num_writers)
        self.num_readers = self.runner.num_readers
        self.num_writers = self.runner.num_writers
        mylog.info("Rockstar is using %d readers and %d writers",
            self.num_readers, self.num_writers)
        # Note that Rockstar does not support subvolumes.
        # We assume that all of the snapshots in the time series
        # use the same domain info as the first snapshots.
        if not isinstance(ts, TimeSeriesData):
            ts = TimeSeriesData([ts])
        self.ts = ts
        self.particle_type = particle_type
        self.outbase = outbase
        if force_res is None:
            tpf = ts[-1] # Cache a reference
            self.force_res = tpf.h.get_smallest_dx() * tpf['mpch']
            # We have to delete now to wipe the hierarchy
            del tpf
        else:
            self.force_res = force_res
        self.total_particles = total_particles
        self.dm_only = dm_only
        self.particle_mass = particle_mass
        # Setup pool and workgroups.
        self.pool, self.workgroup = self.runner.setup_pool()
        p = self._setup_parameters(ts)
        params = self.comm.mpi_bcast(p, root = self.pool['readers'].ranks[0])
        self.__dict__.update(params)
        self.handler = rockstar_interface.RockstarInterface(self.ts)

    def _setup_parameters(self, ts):
        if self.workgroup.name != "readers": return None
        tpf = ts[0]
        ptype = self.particle_type
        if ptype not in tpf.particle_types and ptype != 'all':
            has_particle_filter = tpf.add_particle_filter(ptype)
            if not has_particle_filter:
                raise RuntimeError("Particle type (filter) %s not found." % (ptype))

        dd = tpf.h.all_data()
        # Get DM particle mass.
        all_fields = set(tpf.h.derived_field_list + tpf.h.field_list)
        has_particle_type = ("particle_type" in all_fields)

        particle_mass = self.particle_mass
        if particle_mass is None:
            pmass_min, pmass_max = dd.quantities["Extrema"](
                (ptype, "ParticleMassMsun"), non_zero = True)[0]
            if pmass_min != pmass_max:
                raise YTRockstarMultiMassNotSupported(pmass_min, pmass_max,
                    ptype)
            particle_mass = pmass_min
        # NOTE: We want to take our Msun and turn it into Msun/h .  Its value
        # should be such that dividing by little h gives the original value.
        particle_mass *= tpf.hubble_constant

        p = {}
        if self.total_particles is None:
            # Get total_particles in parallel.
            tp = dd.quantities['TotalQuantity']((ptype, "particle_ones"))[0]
            p['total_particles'] = int(tp)
            mylog.warning("Total Particle Count: %0.3e", int(tp))
        p['left_edge'] = tpf.domain_left_edge
        p['right_edge'] = tpf.domain_right_edge
        p['center'] = (tpf.domain_right_edge + tpf.domain_left_edge)/2.0
        p['particle_mass'] = self.particle_mass = particle_mass
        del tpf
        return p

    def __del__(self):
        try:
            self.pool.free_all()
        except AttributeError:
            # This really only acts to cut down on the misleading
            # error messages when/if this class is called incorrectly
            # or some other error happens and self.pool hasn't been created
            # already.
            pass

    def _get_hosts(self):
        if self.comm.rank == 0 or self.comm.size == 1:
            
            #Temporary mac hostname fix
            try:
                server_address = socket.gethostname()
                socket.gethostbyname(server_address)
            except socket.gaierror:
                server_address = "localhost"

            sock = socket.socket()
            sock.bind(('', 0))
            port = sock.getsockname()[-1]
            del sock
        else:
            server_address, port = None, None
        self.server_address, self.port = self.comm.mpi_bcast(
            (server_address, port))
        self.port = str(self.port)

    def run(self, block_ratio = 1, callbacks = None, restart = False):
        """
        
        """
        if block_ratio != 1:
            raise NotImplementedError
        self._get_hosts()
        # Find restart output number
        num_outputs = len(self.ts)
        if restart:
            restart_file = os.path.join(self.outbase, "restart.cfg")
            if not os.path.exists(restart_file):
                raise RuntimeError("Restart file %s not found" % (restart_file))
            with open(restart_file) as restart_fh:
                for l in restart_fh:
                    if l.startswith("RESTART_SNAP"):
                        restart_num = int(l.split("=")[1])
                    if l.startswith("NUM_WRITERS"):
                        num_writers = int(l.split("=")[1])
            if num_writers != self.num_writers:
                raise RuntimeError(
                    "Number of writers in restart has changed from the original "
                    "run (OLD = %d, NEW = %d).  To avoid problems in the "
                    "restart, choose the same number of writers." % \
                        (num_writers, self.num_writers))
            # Remove the datasets that were already analyzed
            self.ts._pre_outputs = self.ts._pre_outputs[restart_num:]
        else:
            restart_num = 0
        self.handler.setup_rockstar(self.server_address, self.port,
                    num_outputs, self.total_particles, 
                    self.particle_type,
                    particle_mass = self.particle_mass,
                    parallel = self.comm.size > 1,
                    num_readers = self.num_readers,
                    num_writers = self.num_writers,
                    writing_port = -1,
                    block_ratio = block_ratio,
                    outbase = self.outbase,
                    force_res = self.force_res,
                    callbacks = callbacks,
                    restart_num = restart_num)
        # Make the directory to store the halo lists in.
        if not self.outbase:
            self.outbase = os.getcwd()
        if self.comm.rank == 0 and not restart:
            if not os.path.exists(self.outbase):
                os.makedirs(self.outbase)
            # Make a record of which dataset corresponds to which set of
            # output files because it will be easy to lose this connection.
            fp = open(self.outbase + '/pfs.txt', 'w')
            fp.write("# pfname\tindex\n")
            for i, pf in enumerate(self.ts):
                pfloc = path.join(path.relpath(pf.fullpath), pf.basename)
                line = "%s\t%d\n" % (pfloc, i)
                fp.write(line)
            fp.close()
        # This barrier makes sure the directory exists before it might be used.
        self.comm.barrier()
        if self.comm.size == 1:
            self.handler.call_rockstar()
        else:
            # And run it!
            self.runner.run(self.handler, self.workgroup)
        self.comm.barrier()
        self.pool.free_all()
    
    def halo_list(self,file_name='out_0.list'):
        """
        Reads in the out_0.list file and generates RockstarHaloList
        and RockstarHalo objects.
        """
        return RockstarHaloList(self.ts[0], self.outbase+'/%s'%file_name)