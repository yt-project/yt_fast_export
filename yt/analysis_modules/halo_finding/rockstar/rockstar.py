"""
Operations to get Rockstar loaded up

Author: Matthew Turk <matthewturk@gmail.com>
Affiliation: Columbia University
Homepage: http://yt.enzotools.org/
License:
  Copyright (C) 2011 Matthew Turk.  All Rights Reserved.

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

from yt.mods import *
from yt.utilities.parallel_tools.parallel_analysis_interface import \
    ParallelAnalysisInterface, ProcessorPool, Communicator
from yt.analysis_modules.halo_finding.halo_objects import * #Halos & HaloLists
from yt.config import ytcfg

import rockstar_interface

import socket
import time
import threading
import signal
import os
from os import environ
from os import mkdir
from os import path

# Get some definitions from Rockstar directly.
ROCKSTAR_DIR = environ['ROCKSTAR_DIR']
lines = file(path.join(ROCKSTAR_DIR, 'server.h'))
READER_TYPE = None
WRITER_TYPE = None
for line in lines:
    if "READER_TYPE" in line:
        line = line.split()
        READER_TYPE = int(line[-1])
    if "WRITER_TYPE" in line:
        line = line.split()
        WRITER_TYPE = int(line[-1])
    if READER_TYPE != None and WRITER_TYPE != None:
        break
lines.close()

class InlineRunner(ParallelAnalysisInterface):
    def __init__(self, num_writers):
        # If this is being run inline, num_readers == comm.size, always.
        self.num_readers = ytcfg.getint("yt", "__global_parallel_size")
        if num_writers is None:
            self.num_writers =  ytcfg.getint("yt", "__global_parallel_size")
        else:
            self.num_writers = min(num_writers,
                ytcfg.getint("yt", "__global_parallel_size"))

    def split_work(self, pool):
        avail = range(pool.comm.size)
        self.writers = []
        self.readers = []
        # If we're inline, everyone is a reader.
        self.readers = avail[:]
        if self.num_writers == pool.comm.size:
            # And everyone is a writer!
            self.writers = avail[:]
        else:
            # Everyone is not a writer.
            # Cyclically assign writers which should approximate
            # memory load balancing (depending on the mpirun call,
            # but this should do it in most cases).
            stride = int(ceil(float(pool.comm.size) / self.num_writers))
            while len(self.writers) < self.num_writers:
                self.writers.extend(avail[::stride])
                for r in readers:
                    avail.pop(avail.index(r))

    def run(self, handler, pool):
        # If inline, we use forks.
        server_pid = 0
        # Start a server on only one machine/fork.
        if pool.comm.rank == 0:
            server_pid = os.fork()
            if server_pid == 0:
                handler.start_server()
                os._exit(0)
        # Start writers.
        writer_pid = 0
        if pool.comm.rank in self.writers:
            time.sleep(0.1 + pool.comm.rank/10.0)
            writer_pid = os.fork()
            if writer_pid == 0:
                handler.start_client(WRITER_TYPE)
                os._exit(0)
        # Start readers, not forked.
        if pool.comm.rank in self.readers:
            time.sleep(0.1 + pool.comm.rank/10.0)
            handler.start_client(READER_TYPE)
        # Make sure the forks are done, which they should be.
        if writer_pid != 0:
            os.waitpid(writer_pid, 0)
        if server_pid != 0:
            os.waitpid(server_pid, 0)

class StandardRunner(ParallelAnalysisInterface):
    def __init__(self, num_readers, num_writers):
        self.num_readers = num_readers
        if num_writers is None:
            self.num_writers = ytcfg.getint("yt", "__global_parallel_size") \
                - num_readers - 1
        else:
            self.num_writers = min(num_writers,
                ytcfg.getint("yt", "__global_parallel_size"))
        if self.num_readers + self.num_writers + 1 != ytcfg.getint("yt", \
                "__global_parallel_size"):
            mylog.error('%i reader + %i writers != %i mpi',
                    self.num_readers, self.num_writers,
                    ytcfg.getint("yt", "__global_parallel_size"))
            raise RuntimeError
    
    def split_work(self, pool):
        # Who is going to do what.
        avail = range(pool.comm.size)
        self.writers = []
        self.readers = []
        # If we're not running inline, rank 0 should be removed immediately.
        avail.pop(0)
        # Now we assign the rest.
        for i in range(self.num_readers):
            self.readers.append(avail.pop(0))
        for i in range(self.num_writers):
            self.writers.append(avail.pop(0))
    
    def run(self, handler, pool):
        # Not inline so we just launch them directly from our MPI threads.
        if pool.comm.rank == 0:
            handler.start_server()
        if pool.comm.rank in self.readers:
            time.sleep(0.1 + pool.comm.rank/10.0)
            handler.start_client(READER_TYPE)
        if pool.comm.rank in self.writers:
            time.sleep(0.2 + pool.comm.rank/10.0)
            handler.start_client(WRITER_TYPE)

class RockstarHaloFinder(ParallelAnalysisInterface):
    def __init__(self, ts, num_readers = 1, num_writers = None, 
            outbase=None,particle_mass=-1.0,dm_type=1,force_res=None):
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
        particle_mass: float
            This sets the DM particle mass used in Rockstar.
        dm_type: 1
            In order to exclude stars and other particle types, define
            the dm_type. Default is 1, as Enzo has the DM particle type=1.
        force_res: float
            This parameter specifies the force resolution that Rockstar uses
            in units of Mpc/h.
            If no value is provided, this parameter is automatically set to
            the width of the smallest grid element in the simulation from the
            last data snapshot (i.e. the one where time has evolved the
            longest) in the time series:
            ``pf_last.h.get_smallest_dx() * pf_last['mpch']``.
            
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

        files = glob.glob('/u/cmoody3/data/a*')
        files.sort()
        ts = TimeSeriesData.from_filenames(files)
        pm = 7.81769027e+11
        rh = RockstarHaloFinder(ts, particle_mass=pm)
        rh.run()
        """
        # Decide how we're working.
        if ytcfg.getboolean("yt", "inline") == True:
            self.runner = InlineRunner(num_writers)
        else:
            self.runner = StandardRunner(num_readers, num_writers)
        self.num_readers = self.runner.num_readers
        self.num_writers = self.runner.num_writers
        mylog.info("Rockstar is using %d readers and %d writers",
            self.num_readers, self.num_writers)
        # Note that Rockstar does not support subvolumes.
        # We assume that all of the snapshots in the time series
        # use the same domain info as the first snapshots.
        if not isinstance(ts,TimeSeriesData):
            ts = TimeSeriesData([ts])
        self.ts = ts
        self.dm_type = dm_type
        tpf = ts.__iter__().next()
        def _particle_count(field, data):
            try:
                return (data["particle_type"]==dm_type).sum()
            except KeyError:
                return np.prod(data["particle_position_x"].shape)
        add_field("particle_count",function=_particle_count, not_in_all=True,
            particle_type=True)
        # Get total_particles in parallel.
        dd = tpf.h.all_data()
        self.total_particles = int(dd.quantities['TotalQuantity']('particle_count')[0])
        self.hierarchy = tpf.h
        self.particle_mass = particle_mass 
        self.center = (tpf.domain_right_edge + tpf.domain_left_edge)/2.0
        if outbase is None:
            outbase = 'rockstar_halos'
        self.outbase = outbase
        self.particle_mass = particle_mass
        if force_res is None:
            self.force_res = ts[-1].h.get_smallest_dx() * ts[-1]['mpch']
        else:
            self.force_res = force_res
        self.left_edge = tpf.domain_left_edge
        self.right_edge = tpf.domain_right_edge
        self.center = (tpf.domain_right_edge + tpf.domain_left_edge)/2.0
        # We set up the workgroups *before* initializing
        # ParallelAnalysisInterface. Everyone is their own workgroup!
        self.pool = ProcessorPool()
        for i in range(ytcfg.getint("yt", "__global_parallel_size")):
             self.pool.add_workgroup(size=1)
        ParallelAnalysisInterface.__init__(self)
        for wg in self.pool.workgroups:
            if self.pool.comm.rank in wg.ranks:
                self.workgroup = wg
        self.handler = rockstar_interface.RockstarInterface(
                self.ts, dd)

    def __del__(self):
        self.pool.free_all()

    def _get_hosts(self):
        if self.pool.comm.size == 1 or self.pool.comm.rank == 0:
            server_address = socket.gethostname()
            sock = socket.socket()
            sock.bind(('', 0))
            port = sock.getsockname()[-1]
            del sock
        else:
            server_address, port = None, None
        self.server_address, self.port = self.pool.comm.mpi_bcast(
            (server_address, port))
        self.port = str(self.port)

    def run(self, block_ratio = 1,**kwargs):
        """
        
        """
        if block_ratio != 1:
            raise NotImplementedError
        self._get_hosts()
        self.handler.setup_rockstar(self.server_address, self.port,
                    len(self.ts), self.total_particles, 
                    self.dm_type,
                    parallel = self.pool.comm.size > 1,
                    num_readers = self.num_readers,
                    num_writers = self.num_writers,
                    writing_port = -1,
                    block_ratio = block_ratio,
                    outbase = self.outbase,
                    force_res=self.force_res,
                    particle_mass = float(self.particle_mass),
                    **kwargs)
        # Make the directory to store the halo lists in.
        if self.pool.comm.rank == 0:
            if not os.path.exists(self.outbase):
                os.mkdir(self.outbase)
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
        self.pool.comm.barrier()
        if self.pool.comm.size == 1:
            self.handler.call_rockstar()
        else:
            # Split up the work.
            self.runner.split_work(self.pool)
            # And run it!
            self.runner.run(self.handler, self.pool)
        self.pool.comm.barrier()
        self.pool.free_all()
    
    def halo_list(self,file_name='out_0.list'):
        """
        Reads in the out_0.list file and generates RockstarHaloList
        and RockstarHalo objects.
        """
        return RockstarHaloList(self.pf,self.outbase+'/%s'%file_name)
