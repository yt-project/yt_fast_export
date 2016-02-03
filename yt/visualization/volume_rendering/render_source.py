"""
RenderSource Class

"""

# -----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
# -----------------------------------------------------------------------------

import numpy as np
from yt.funcs import mylog, ensure_numpy_array
from yt.utilities.parallel_tools.parallel_analysis_interface import \
    ParallelAnalysisInterface
from yt.utilities.amr_kdtree.api import AMRKDTree
from .transfer_function_helper import TransferFunctionHelper
from .transfer_functions import TransferFunction, \
    ProjectionTransferFunction, ColorTransferFunction
from .utils import new_volume_render_sampler, data_source_or_all, \
    get_corners, new_projection_sampler, new_mesh_sampler
from yt.visualization.image_writer import apply_colormap
from yt.data_objects.image_array import ImageArray
from .zbuffer_array import ZBuffer
from yt.utilities.lib.misc_utilities import \
    zlines, zpoints

from yt.utilities.on_demand_imports import NotAModule
try:
    from yt.utilities.lib import mesh_traversal
except ImportError:
    mesh_traversal = NotAModule("pyembree")
try:
    from yt.utilities.lib import mesh_construction
except ImportError:
    mesh_construction = NotAModule("pyembree")


class RenderSource(ParallelAnalysisInterface):

    """Base Class for Render Sources.

    Will be inherited for volumes, streamlines, etc.

    """

    def __init__(self):
        super(RenderSource, self).__init__()
        self.opaque = False
        self.zbuffer = None

    def render(self, camera, zbuffer=None):
        pass

    def _validate(self):
        pass


class OpaqueSource(RenderSource):
    """A base class for opaque render sources.

    Will be inherited from for LineSources, BoxSources, etc.

    """
    def __init__(self):
        super(OpaqueSource, self).__init__()
        self.opaque = True

    def set_zbuffer(self, zbuffer):
        self.zbuffer = zbuffer


class VolumeSource(RenderSource):
    """A class for rendering data from a volumetric data source

    Examples of such sources include a sphere, cylinder, or the
    entire computational domain.

    A :class:`VolumeSource` provides the framework to decompose an arbitrary
    yt data source into bricks that can be traversed and volume rendered.

    Parameters
    ----------
    data_source: :class:`AMR3DData` or :class:`Dataset`, optional
        This is the source to be rendered, which can be any arbitrary yt
        data object or dataset.
    fields : string
        The name of the field(s) to be rendered.
    auto: bool, optional
        If True, will build a default AMRKDTree and transfer function based
        on the data.

    Examples
    --------

    The easiest way to make a VolumeSource is to use the volume_render
    function, so that the VolumeSource gets created automatically. This 
    example shows how to do this and then access the resulting source:

    >>> import yt
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>> im, sc = yt.volume_render(ds)
    >>> volume_source = sc.get_source(0)

    You can also create VolumeSource instances by hand and add them to Scenes.
    This example manually creates a VolumeSource, adds it to a scene, sets the
    camera, and renders an image.

    >>> import yt
    >>> from yt.visualization.volume_rendering.api import Scene, VolumeSource, Camera
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>> sc = Scene()
    >>> source = VolumeSource(ds.all_data(), 'density')
    >>> sc.add_source(source)
    >>> cam = Camera(ds)
    >>> sc.camera = cam
    >>> im = sc.render()

    """

    _image = None
    data_source = None

    def __init__(self, data_source, field, auto=True):
        r"""Initialize a new volumetric source for rendering."""
        super(VolumeSource, self).__init__()
        self.data_source = data_source_or_all(data_source)
        field = self.data_source._determine_fields(field)[0]
        self.field = field
        self.volume = None
        self.current_image = None
        self.double_check = False
        self.num_threads = 0
        self.num_samples = 10
        self.sampler_type = 'volume-render'

        # Error checking
        assert(self.field is not None)
        assert(self.data_source is not None)

        # In the future these will merge
        self.transfer_function = None
        self.tfh = None
        if auto:
            self.build_defaults()

    def build_defaults(self):
        """Sets a default volume and transfer function"""
        mylog.info("Creating default volume")
        self.build_default_volume()
        mylog.info("Creating default transfer function")
        self.build_default_transfer_function()

    def set_transfer_function(self, transfer_function):
        """Set transfer function for this source"""
        if not isinstance(transfer_function,
                          (TransferFunction, ColorTransferFunction,
                           ProjectionTransferFunction)):
            raise RuntimeError("transfer_function not of correct type")
        if isinstance(transfer_function, ProjectionTransferFunction):
            self.sampler_type = 'projection'

        self.transfer_function = transfer_function
        return self

    def _validate(self):
        """Make sure that all dependencies have been met"""
        if self.data_source is None:
            raise RuntimeError("Data source not initialized")

        if self.volume is None:
            raise RuntimeError("Volume not initialized")

        if self.transfer_function is None:
            raise RuntimeError("Transfer Function not Supplied")

    def build_default_transfer_function(self):
        """Sets up a transfer function"""
        self.tfh = \
            TransferFunctionHelper(self.data_source.pf)
        self.tfh.set_field(self.field)
        self.tfh.build_transfer_function()
        self.tfh.setup_default()
        self.transfer_function = self.tfh.tf

    def build_default_volume(self):
        """Sets up an AMRKDTree based on the VolumeSource's field"""
        self.volume = AMRKDTree(self.data_source.pf,
                                data_source=self.data_source)
        log_fields = [self.data_source.pf.field_info[self.field].take_log]
        mylog.debug('Log Fields:' + str(log_fields))
        self.volume.set_fields([self.field], log_fields, True)

    def set_volume(self, volume):
        """Associates an AMRKDTree with the VolumeSource"""
        assert(isinstance(volume, AMRKDTree))
        del self.volume
        self.volume = volume

    def set_fields(self, fields, no_ghost=True):
        """Set the source's fields to render

        Parameters
        ---------
        fields: field name or list of field names
            The field or fields to render
        no_ghost: boolean
            If False, the AMRKDTree estimates vertex centered data using ghost
            zones, which can eliminate seams in the resulting volume rendering.
            Defaults to True for performance reasons.
        """
        fields = self.data_source._determine_fields(fields)
        log_fields = [self.data_source.ds.field_info[f].take_log
                      for f in fields]
        self.volume.set_fields(fields, log_fields, no_ghost)
        self.field = fields

    def set_sampler(self, camera):
        """Sets a volume render sampler

        The type of sampler is determined based on the ``sampler_type`` attribute
        of the VolumeSource. Currently the ``volume_render`` and ``projection``
        sampler types are supported.
        """
        if self.sampler_type == 'volume-render':
            sampler = new_volume_render_sampler(camera, self)
        elif self.sampler_type == 'projection':
            sampler = new_projection_sampler(camera, self)
        else:
            NotImplementedError("%s not implemented yet" % self.sampler_type)
        self.sampler = sampler
        assert(self.sampler is not None)

    def render(self, camera, zbuffer=None):
        """Renders an image using the provided camera

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            A volume rendering camera. Can be any type of camera.
        zbuffer: :class:`yt.visualization.volume_rendering.zbuffer_array.Zbuffer` instance
            A zbuffer array. This is used for opaque sources to determine the
            z position of the source relative to other sources. Only useful if
            you are manually calling render on multiple sources. Scene.render
            uses this internally.

        Returns
        -------
        A :class:`yt.data_objects.image_array.ImageArray` instance containing
        the rendered image.

        """
        self.zbuffer = zbuffer
        self.set_sampler(camera)
        assert (self.sampler is not None)

        mylog.debug("Casting rays")
        total_cells = 0
        if self.double_check:
            for brick in self.volume.bricks:
                for data in brick.my_data:
                    if np.any(np.isnan(data)):
                        raise RuntimeError

        for brick in self.volume.traverse(camera.lens.viewpoint):
            mylog.debug("Using sampler %s" % self.sampler)
            self.sampler(brick, num_threads=self.num_threads)
            total_cells += np.prod(brick.my_data[0].shape)
        mylog.debug("Done casting rays")

        self.current_image = self.finalize_image(camera,
                                                 self.sampler.aimage,
                                                 call_from_VR=True)
        if zbuffer is None:
            self.zbuffer = ZBuffer(self.current_image,
                                   np.inf*np.ones(self.current_image.shape[:2]))
        return self.current_image

    def finalize_image(self, camera, image, call_from_VR=False):
        """Parallel reduce the image.

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            The camera used to produce the volume rendering image.
        image: :class:`yt.data_objects.image_array.ImageArray` instance
            A reference to an image to fill
        call_from_vr: boolean, optional
            Whether or not this is being called from a higher level in the VR
            interface. Used to set the correct orientation.
        """
        image = self.volume.reduce_tree_images(image, camera.lens.viewpoint)
        image.shape = camera.resolution[0], camera.resolution[1], 4
        # If the call is from VR, the image is rotated by 180 to get correct
        # up direction
        if call_from_VR is True: 
            image = np.rot90(image, k=2)
        if self.transfer_function.grey_opacity is False:
            image[:, :, 3] = 1.0
        return image

    def __repr__(self):
        disp = "<Volume Source>:%s " % str(self.data_source)
        disp += "transfer_function:%s" % str(self.transfer_function)
        return disp


class MeshSource(OpaqueSource):
    """A source for unstructured mesh data.

    This functionality requires the embree ray-tracing engine and the
    associated pyembree python bindings to be installed in order to
    function.

    A :class:`MeshSource` provides the framework to volume render
    unstructured mesh data.

    Parameters
    ----------
    data_source: :class:`AMR3DData` or :class:`Dataset`, optional
        This is the source to be rendered, which can be any arbitrary yt
        data object or dataset.
    field : string
        The name of the field to be rendered.

    Examples
    --------
    >>> source = MeshSource(ds, ('connect1', 'convected'))
    """

    _image = None
    data_source = None

    def __init__(self, data_source, field):
        r"""Initialize a new unstructured mesh source for rendering."""
        super(MeshSource, self).__init__()
        self.data_source = data_source_or_all(data_source)
        field = self.data_source._determine_fields(field)[0]
        self.field = field
        self.mesh = None
        self.current_image = None

        # default color map
        self._cmap = 'algae'
        self._color_bounds = None

        # default mesh annotation options
        self._annotate_mesh = False
        self._mesh_line_color = None
        self._mesh_line_alpha = 1.0

        # Error checking
        assert(self.field is not None)
        assert(self.data_source is not None)

        self.scene = mesh_traversal.YTEmbreeScene()
        self.build_mesh()

    def cmap():
        '''
        This is the name of the colormap that will be used when rendering
        this MeshSource object. Should be a string, like 'algae', or 'hot'.
        
        '''

        def fget(self):
            return self._cmap

        def fset(self, cmap_name):
            self._cmap = cmap_name
            if hasattr(self, "data"):
                self.current_image = self.apply_colormap()
        return locals()
    cmap = property(**cmap())

    def color_bounds():
        '''
        These are the bounds that will be used with the colormap to the display
        the rendered image. Should be a (vmin, vmax) tuple, like (0.0, 2.0). If
        None, the bounds will be automatically inferred from the max and min of 
        the rendered data.

        '''
        def fget(self):
            return self._color_bounds

        def fset(self, bounds):
            self._color_bounds = bounds
            if hasattr(self, "data"):
                self.current_image = self.apply_colormap()
        return locals()
    color_bounds = property(**color_bounds())

    def _validate(self):
        """Make sure that all dependencies have been met"""
        if self.data_source is None:
            raise RuntimeError("Data source not initialized")

        if self.mesh is None:
            raise RuntimeError("Mesh not initialized")

    def build_mesh(self):
        """

        This constructs the mesh that will be ray-traced.

        """
        ftype, fname = self.field
        mesh_id = int(ftype[-1]) - 1
        index = self.data_source.ds.index
        offset = index.meshes[mesh_id]._index_offset
        field_data = self.data_source[self.field].d  # strip units

        vertices = index.meshes[mesh_id].connectivity_coords
        indices = index.meshes[mesh_id].connectivity_indices - offset

        # if this is an element field, promote to 2D here
        if len(field_data.shape) == 1:
            field_data = np.expand_dims(field_data, 1)

        # Here, we decide whether to render based on high-order or 
        # low-order geometry. Right now, high-order geometry is only
        # implemented for 20-point hexes.
        if indices.shape[1] == 20:
            self.mesh = mesh_construction.QuadraticElementMesh(self.scene,
                                                               vertices,
                                                               indices,
                                                               field_data)
        else:
            # if this is another type of higher-order element, we demote
            # to 1st order here, for now.
            if indices.shape[1] == 27:
                # hexahedral
                mylog.warning("27-node hexes not yet supported, " +
                              "dropping to 1st order.")
                field_data = field_data[:, 0:8]
                indices = indices[:, 0:8]
            elif indices.shape[1] == 10:
                # tetrahedral
                mylog.warning("10-node tetrahedral elements not yet supported, " +
                              "dropping to 1st order.")
                field_data = field_data[:, 0:4]
                indices = indices[:, 0:4]

            self.mesh = mesh_construction.LinearElementMesh(self.scene,
                                                            vertices,
                                                            indices,
                                                            field_data)

    def render(self, camera, zbuffer=None):
        """Renders an image using the provided camera

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            A volume rendering camera. Can be any type of camera.
        zbuffer: :class:`yt.visualization.volume_rendering.zbuffer_array.Zbuffer` instance
            A zbuffer array. This is used for opaque sources to determine the
            z position of the source relative to other sources. Only useful if
            you are manually calling render on multiple sources. Scene.render
            uses this internally.

        Returns
        -------
        A :class:`yt.data_objects.image_array.ImageArray` instance containing
        the rendered image.

        """

        shape = (camera.resolution[0], camera.resolution[1], 4)
        if zbuffer is None:
            empty = np.empty(shape, dtype='float64')
            z = np.empty(empty.shape[:2], dtype='float64')
            empty[:] = 0.0
            z[:] = np.inf
            zbuffer = ZBuffer(empty, z)
        elif zbuffer.rgba.shape != shape:
            zbuffer = ZBuffer(zbuffer.rgba.reshape(shape),
                              zbuffer.z.reshape(shape[:2]))
        self.zbuffer = zbuffer

        self.sampler = new_mesh_sampler(camera, self)

        mylog.debug("Casting rays")
        self.sampler(self.scene)
        mylog.debug("Done casting rays")

        self.finalize_image(camera)
        self.data = self.sampler.aimage
        self.current_image = self.apply_colormap()

        zbuffer += ZBuffer(self.current_image.astype('float64'),
                           self.sampler.zbuffer)
        zbuffer.rgba = ImageArray(zbuffer.rgba)
        self.zbuffer = zbuffer
        self.current_image = self.zbuffer.rgba

        if self._annotate_mesh:
            self.current_image = self.annotate_mesh_lines(self._mesh_line_color,
                                                          self._mesh_line_alpha)

        return self.current_image

    def finalize_image(self, camera):
        sam = self.sampler

        # reshape data
        Nx = camera.resolution[0]
        Ny = camera.resolution[1]
        sam.aimage = sam.aimage.reshape(Nx, Ny)
        sam.image_used = sam.image_used.reshape(Nx, Ny)
        sam.mesh_lines = sam.mesh_lines.reshape(Nx, Ny)
        sam.zbuffer = sam.zbuffer.reshape(Nx, Ny)

        # rotate
        sam.aimage = np.rot90(sam.aimage, k=2)
        sam.image_used = np.rot90(sam.image_used, k=2)
        sam.mesh_lines = np.rot90(sam.mesh_lines, k=2)
        sam.zbuffer = np.rot90(sam.zbuffer, k=2)

    def annotate_mesh_lines(self, color=None, alpha=1.0):
        r"""

        Modifies this MeshSource by drawing the mesh lines.
        This modifies the current image by drawing the element
        boundaries and returns the modified image.

        Parameters
        ----------
        color: array of ints, shape (4), optional
            The RGBA value to use to draw the mesh lines.
            Default is black.
        alpha : float, optional
            The opacity of the mesh lines. Default is 255 (solid).

        """

        self.annotate_mesh = True
        self._mesh_line_color = color
        self._mesh_line_alpha = alpha

        if color is None:
            color = np.array([0, 0, 0, alpha])

        locs = [self.sampler.mesh_lines == 1]

        self.current_image[:, :, 0][locs] = color[0]
        self.current_image[:, :, 1][locs] = color[1]
        self.current_image[:, :, 2][locs] = color[2]
        self.current_image[:, :, 3][locs] = color[3]

        return self.current_image

    def apply_colormap(self):
        '''

        Applies a colormap to the current image without re-rendering.

        Parameters
        ----------
        cmap_name : string, optional
            An acceptable colormap.  See either yt.visualization.color_maps or
            http://www.scipy.org/Cookbook/Matplotlib/Show_colormaps .
        color_bounds : tuple of floats, optional
            The min and max to scale between.  Outlying values will be clipped.

        Returns
        -------
        current_image : A new image with the specified color scale applied to
            the underlying data.


        '''

        image = apply_colormap(self.data,
                               color_bounds=self._color_bounds,
                               cmap_name=self._cmap)/255.
        alpha = image[:, :, 3]
        alpha[self.sampler.image_used == -1] = 0.0
        image[:, :, 3] = alpha        
        return image

    def __repr__(self):
        disp = "<Mesh Source>:%s " % str(self.data_source)
        return disp


class PointSource(OpaqueSource):
    r"""A rendering source of opaque points in the scene.

    This class provides a mechanism for adding points to a scene; these
    points will be opaque, and can also be colored.

    Parameters
    ----------
    positions: array, shape (N, 3)
        These positions, in data-space coordinates, are the points to be
        added to the scene.
    colors : array, shape (N, 4), optional
        The colors of the points, including an alpha channel, in floating
        point running from 0..1.
    color_stride : int, optional
        The stride with which to access the colors when putting them on the
        scene.

    Examples
    --------

    This example creates a volume rendering and adds 1000 random points to
    the image:

    >>> import yt
    >>> import numpy as np
    >>> from yt.visualization.volume_rendering.api import PointSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    
    >>> im, sc = yt.volume_render(ds)
    
    >>> npoints = 1000
    >>> vertices = np.random.random([npoints, 3])
    >>> colors = np.random.random([npoints, 4])
    >>> colors[:,3] = 1.0

    >>> points = PointSource(vertices, colors=colors)
    >>> sc.add_source(points)
    
    >>> im = sc.render()

    """


    _image = None
    data_source = None

    def __init__(self, positions, colors=None, color_stride=1):
        assert(positions.ndim == 2 and positions.shape[1] == 3)
        if colors is not None:
            assert(colors.ndim == 2 and colors.shape[1] == 4)
            assert(colors.shape[0] == positions.shape[0]) 
        self.positions = positions
        # If colors aren't individually set, make black with full opacity
        if colors is None:
            colors = np.ones((len(positions), 4))
            colors[:, 3] = 1.
        self.colors = colors
        self.color_stride = color_stride

    def render(self, camera, zbuffer=None):
        """Renders an image using the provided camera

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            A volume rendering camera. Can be any type of camera.
        zbuffer: :class:`yt.visualization.volume_rendering.zbuffer_array.Zbuffer` instance
            A zbuffer array. This is used for opaque sources to determine the
            z position of the source relative to other sources. Only useful if
            you are manually calling render on multiple sources. Scene.render
            uses this internally.

        Returns
        -------
        A :class:`yt.data_objects.image_array.ImageArray` instance containing
        the rendered image.

        """
        vertices = self.positions
        if zbuffer is None:
            empty = camera.lens.new_image(camera)
            z = np.empty(empty.shape[:2], dtype='float64')
            empty[:] = 0.0
            z[:] = np.inf
            zbuffer = ZBuffer(empty, z)
        else:
            empty = zbuffer.rgba
            z = zbuffer.z

        # DRAW SOME POINTS
        camera.lens.setup_box_properties(camera)
        px, py, dz = camera.lens.project_to_plane(camera, vertices)

        # Non-plane-parallel lenses only support 1D array
        # 1D array needs to be transformed to 2D to get points plotted
        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0], camera.resolution[1], 4)
            z.shape = (camera.resolution[0], camera.resolution[1])

        zpoints(empty, z, px.d, py.d, dz.d, self.colors, self.color_stride)

        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0] * camera.resolution[1], 1, 4)
            z.shape = (camera.resolution[0] * camera.resolution[1], 1)

        self.zbuffer = zbuffer
        return zbuffer

    def __repr__(self):
        disp = "<Point Source>"
        return disp


class LineSource(OpaqueSource):
    r"""A render source for a sequence of opaque line segments.

    This class provides a mechanism for adding lines to a scene; these
    points will be opaque, and can also be colored.

    Parameters
    ----------
    positions: array, shape (N, 2, 3)
        These positions, in data-space coordinates, are the starting and
        stopping points for each pair of lines. For example,
        positions[0][0] and positions[0][1] would give the (x, y, z)
        coordinates of the beginning and end points of the first line,
        respectively.
    colors : array, shape (N, 4), optional
        The colors of the points, including an alpha channel, in floating
        point running from 0..1.  Note that they correspond to the line
        segment succeeding each point; this means that strictly speaking
        they need only be (N-1) in length.
    color_stride : int, optional
        The stride with which to access the colors when putting them on the
        scene.

    Examples
    --------

    This example creates a volume rendering and then adds some random lines
    to the image:

    >>> import yt
    >>> import numpy as np
    >>> from yt.visualization.volume_rendering.api import LineSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    
    >>> im, sc = yt.volume_render(ds)
    
    >>> npoints = 100
    >>> vertices = np.random.random([npoints, 2, 3])
    >>> colors = np.random.random([npoints, 4])
    >>> colors[:,3] = 1.0
    
    >>> lines = LineSource(vertices, colors)
    >>> sc.add_source(lines)

    >>> im = sc.render()
    
    """

    _image = None
    data_source = None

    def __init__(self, positions, colors=None, color_stride=1):
        super(LineSource, self).__init__()

        assert(positions.ndim == 3)
        assert(positions.shape[1] == 2)
        assert(positions.shape[2] == 3)
        if colors is not None:
            assert(colors.ndim == 2)
            assert(colors.shape[1] == 4)

        # convert the positions to the shape expected by zlines, below
        N = positions.shape[0]
        self.positions = positions.reshape((2*N, 3))

        # If colors aren't individually set, make black with full opacity
        if colors is None:
            colors = np.ones((len(positions), 4))
            colors[:, 3] = 1.
        self.colors = colors
        self.color_stride = color_stride

    def render(self, camera, zbuffer=None):
        """Renders an image using the provided camera

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            A volume rendering camera. Can be any type of camera.
        zbuffer: :class:`yt.visualization.volume_rendering.zbuffer_array.Zbuffer` instance
            A zbuffer array. This is used for opaque sources to determine the
            z position of the source relative to other sources. Only useful if
            you are manually calling render on multiple sources. Scene.render
            uses this internally.

        Returns
        -------
        A :class:`yt.data_objects.image_array.ImageArray` instance containing
        the rendered image.

        """
        vertices = self.positions
        if zbuffer is None:
            empty = camera.lens.new_image(camera)
            z = np.empty(empty.shape[:2], dtype='float64')
            empty[:] = 0.0
            z[:] = np.inf
            zbuffer = ZBuffer(empty, z)
        else:
            empty = zbuffer.rgba
            z = zbuffer.z

        # DRAW SOME LINES
        camera.lens.setup_box_properties(camera)
        px, py, dz = camera.lens.project_to_plane(camera, vertices)

        # Non-plane-parallel lenses only support 1D array
        # 1D array needs to be transformed to 2D to get lines plotted
        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0], camera.resolution[1], 4)
            z.shape = (camera.resolution[0], camera.resolution[1])

        if len(px.shape) == 1:
            zlines(empty, z, px.d, py.d, dz.d, self.colors, self.color_stride)
        else:
            # For stereo-lens, two sets of pos for each eye are contained in px...pz
            zlines(empty, z, px.d[0,:], py.d[0,:], dz.d[0,:], self.colors, self.color_stride)
            zlines(empty, z, px.d[1,:], py.d[1,:], dz.d[1,:], self.colors, self.color_stride)

        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0] * camera.resolution[1], 1, 4)
            z.shape = (camera.resolution[0] * camera.resolution[1], 1)

        self.zbuffer = zbuffer
        return zbuffer

    def __repr__(self):
        disp = "<Line Source>"
        return disp


class BoxSource(LineSource):
    r"""A render source for a box drawn with line segments.
    This render source will draw a box, with transparent faces, in data
    space coordinates.  This is useful for annotations.

    Parameters
    ----------
    left_edge: array-like, shape (3,), float
        The left edge coordinates of the box.
    right_edge : array-like, shape (3,), float
        The right edge coordinates of the box.
    color : array-like, shape (4,), float, optional
        The colors (including alpha) to use for the lines.

    Examples
    --------

    This example shows how to use BoxSource to add an outline of the 
    domain boundaries to a volume rendering.

    >>> import yt
    >>> from yt.visualization.volume_rendering.api import BoxSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>>
    >>> im, sc = yt.volume_render(ds)
    >>> 
    >>> box_source = BoxSource(ds.domain_left_edge,
    ...                       ds.domain_right_edge,
    ...                       [1.0, 1.0, 1.0, 1.0])
    >>> sc.add_source(box_source)
    >>> 
    >>> im = sc.render()

    """
    def __init__(self, left_edge, right_edge, color=None):

        assert(left_edge.shape == (3,))
        assert(right_edge.shape == (3,))
        
        if color is None:
            color = np.array([1.0, 1.0, 1.0, 1.0])

        color = ensure_numpy_array(color)
        color.shape = (1, 4)
        corners = get_corners(left_edge.copy(), right_edge.copy())
        order = [0, 1, 1, 2, 2, 3, 3, 0]
        order += [4, 5, 5, 6, 6, 7, 7, 4]
        order += [0, 4, 1, 5, 2, 6, 3, 7]
        vertices = np.empty([24, 3])
        for i in range(3):
            vertices[:, i] = corners[order, i, ...].ravel(order='F')
        vertices = vertices.reshape((12, 2, 3))

        super(BoxSource, self).__init__(vertices, color, color_stride=24)


class GridSource(LineSource):
    r"""A render source for drawing grids in a scene.

    This render source will draw blocks that are within a given data
    source, by default coloring them by their level of resolution.

    Parameters
    ----------
    data_source: :class:`~yt.data_objects.api.DataContainer`
        The data container that will be used to identify grids to draw.
    alpha : float
        The opacity of the grids to draw.
    cmap : color map name
        The color map to use to map resolution levels to color.
    min_level : int, optional
        Minimum level to draw
    max_level : int, optional
        Maximum level to draw

    Examples
    --------

    This example makes a volume rendering and adds outlines of all the 
    AMR grids in the simulation:

    >>> import yt
    >>> from yt.visualization.volume_rendering.api import GridSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>>
    >>> im, sc = yt.volume_render(ds)
    >>>
    >>> grid_source = GridSource(ds.all_data(), alpha=1.0)
    >>>
    >>> sc.add_source(grid_source)
    >>>
    >>> im = sc.render()

    This example does the same thing, except it only draws the grids
    that are inside a sphere of radius (0.1, "unitary") located at the
    domain center:

    >>> import yt
    >>> from yt.visualization.volume_rendering.api import GridSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>> 
    >>> im, sc = yt.volume_render(ds)
    >>> 
    >>> dd = ds.sphere("c", (0.1, "unitary"))
    >>> grid_source = GridSource(dd, alpha=1.0)
    >>> 
    >>> sc.add_source(grid_source)
    >>>
    >>> im = sc.render()

    """

    def __init__(self, data_source, alpha=0.3, cmap='algae',
                 min_level=None, max_level=None):
        data_source = data_source_or_all(data_source)
        corners = []
        levels = []
        for block, mask in data_source.blocks:
            block_corners = np.array([
                [block.LeftEdge[0], block.LeftEdge[1], block.LeftEdge[2]],
                [block.RightEdge[0], block.LeftEdge[1], block.LeftEdge[2]],
                [block.RightEdge[0], block.RightEdge[1], block.LeftEdge[2]],
                [block.LeftEdge[0], block.RightEdge[1], block.LeftEdge[2]],
                [block.LeftEdge[0], block.LeftEdge[1], block.RightEdge[2]],
                [block.RightEdge[0], block.LeftEdge[1], block.RightEdge[2]],
                [block.RightEdge[0], block.RightEdge[1], block.RightEdge[2]],
                [block.LeftEdge[0], block.RightEdge[1], block.RightEdge[2]],
            ], dtype='float64')
            corners.append(block_corners)
            levels.append(block.Level)
        corners = np.dstack(corners)
        levels = np.array(levels)

        if max_level is not None:
            subset = levels <= max_level
            levels = levels[subset]
            corners = corners[:, :, subset]
        if min_level is not None:
            subset = levels >= min_level
            levels = levels[subset]
            corners = corners[:, :, subset]

        colors = apply_colormap(
            levels*1.0,
            color_bounds=[0, data_source.ds.index.max_level],
            cmap_name=cmap)[0, :, :]*alpha/255.
        colors[:, 3] = alpha

        order = [0, 1, 1, 2, 2, 3, 3, 0]
        order += [4, 5, 5, 6, 6, 7, 7, 4]
        order += [0, 4, 1, 5, 2, 6, 3, 7]

        vertices = np.empty([corners.shape[2]*2*12, 3])
        for i in range(3):
            vertices[:, i] = corners[order, i, ...].ravel(order='F')
        vertices = vertices.reshape((corners.shape[2]*12, 2, 3))

        super(GridSource, self).__init__(vertices, colors, color_stride=24)


class CoordinateVectorSource(OpaqueSource):
    r"""Draw coordinate vectors on the scene.

    This will draw a set of coordinate vectors on the camera image.  They
    will appear in the lower right of the image.

    Parameters
    ----------
    colors: array-like, shape (3,4), optional
        The x, y, z RGBA values to use to draw the vectors.
    alpha : float, optional
        The opacity of the vectors.

    Examples
    --------

    >>> import yt
    >>> from yt.visualization.volume_rendering.api import CoordinateVectorSource
    >>> ds = yt.load('IsolatedGalaxy/galaxy0030/galaxy0030')
    >>>
    >>> im, sc = yt.volume_render(ds)
    >>> 
    >>> coord_source = CoordinateVectorSource()
    >>> 
    >>> sc.add_source(coord_source)
    >>> 
    >>> im = sc.render()

    """

    def __init__(self, colors=None, alpha=1.0):
        super(CoordinateVectorSource, self).__init__()
        # If colors aren't individually set, make black with full opacity
        if colors is None:
            colors = np.zeros((3, 4))
            colors[0, 0] = alpha  # x is red
            colors[1, 1] = alpha  # y is green
            colors[2, 2] = alpha  # z is blue
            colors[:, 3] = alpha
        self.colors = colors
        self.color_stride = 2

    def render(self, camera, zbuffer=None):
        """Renders an image using the provided camera

        Parameters
        ----------
        camera: :class:`yt.visualization.volume_rendering.camera.Camera` instance
            A volume rendering camera. Can be any type of camera.
        zbuffer: :class:`yt.visualization.volume_rendering.zbuffer_array.Zbuffer` instance
            A zbuffer array. This is used for opaque sources to determine the
            z position of the source relative to other sources. Only useful if
            you are manually calling render on multiple sources. Scene.render
            uses this internally.

        Returns
        -------
        A :class:`yt.data_objects.image_array.ImageArray` instance containing
        the rendered image.

        """
        camera.lens.setup_box_properties(camera)
        center = camera.focus
        # Get positions at the focus
        positions = np.zeros([6, 3])
        positions[:] = center

        # Create vectors in the x,y,z directions
        for i in range(3):
            positions[2*i+1, i] += camera.width.d[i] / 16.0

        # Project to the image plane
        px, py, dz = camera.lens.project_to_plane(camera, positions)

        if len(px.shape) == 1:
            dpx = px[1::2] - px[::2]
            dpy = py[1::2] - py[::2]

            # Set the center of the coordinates to be in the lower left of the image
            lpx = camera.resolution[0] / 8
            lpy = camera.resolution[1] - camera.resolution[1] / 8  # Upside-downsies

            # Offset the pixels according to the projections above
            px[::2] = lpx
            px[1::2] = lpx + dpx
            py[::2] = lpy
            py[1::2] = lpy + dpy
            dz[:] = 0.0
        else:
            # For stereo-lens, two sets of pos for each eye are contained in px...pz
            dpx = px[:,1::2] - px[:,::2]
            dpy = py[:,1::2] - py[:,::2]

            lpx = camera.resolution[0] / 16
            lpy = camera.resolution[1] - camera.resolution[1] / 8  # Upside-downsies

            # Offset the pixels according to the projections above
            px[:,::2] = lpx
            px[:,1::2] = lpx + dpx
            px[1,:] += camera.resolution[0] / 2
            py[:,::2] = lpy
            py[:,1::2] = lpy + dpy
            dz[:,:] = 0.0

        # Create a zbuffer if needed
        if zbuffer is None:
            empty = camera.lens.new_image(camera)
            z = np.empty(empty.shape[:2], dtype='float64')
            empty[:] = 0.0
            z[:] = np.inf
            zbuffer = ZBuffer(empty, z)
        else:
            empty = zbuffer.rgba
            z = zbuffer.z

        # Draw the vectors

        # Non-plane-parallel lenses only support 1D array
        # 1D array needs to be transformed to 2D to get lines plotted
        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0], camera.resolution[1], 4)
            z.shape = (camera.resolution[0], camera.resolution[1])

        if len(px.shape) == 1:
            zlines(empty, z, px.d, py.d, dz.d, self.colors, self.color_stride)
        else:
            # For stereo-lens, two sets of pos for each eye are contained in px...pz
            zlines(empty, z, px.d[0,:], py.d[0,:], dz.d[0,:], self.colors, self.color_stride)
            zlines(empty, z, px.d[1,:], py.d[1,:], dz.d[1,:], self.colors, self.color_stride)

        if 'plane-parallel' not in str(camera.lens):
            empty.shape = (camera.resolution[0] * camera.resolution[1], 1, 4)
            z.shape = (camera.resolution[0] * camera.resolution[1], 1)

        # Set the new zbuffer
        self.zbuffer = zbuffer
        return zbuffer

    def __repr__(self):
        disp = "<Coordinates Source>"
        return disp
