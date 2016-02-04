import os
import OpenGL.GL as GL
from OpenGL.GL import shaders

import numpy as np
from yt.utilities.math_utils import \
    get_translate_matrix, \
    get_scale_matrix, \
    get_lookat_matrix, \
    get_perspective_matrix, \
    quaternion_mult, \
    quaternion_to_rotation_matrix
    
bbox_vertices = np.array(
      [[ 0.,  0.,  0.,  1.],
       [ 0.,  0.,  1.,  1.],
       [ 0.,  1.,  1.,  1.],
       [ 1.,  1.,  0.,  1.],
       [ 0.,  0.,  0.,  1.],
       [ 0.,  1.,  0.,  1.],
       [ 1.,  0.,  1.,  1.],
       [ 0.,  0.,  0.,  1.],
       [ 1.,  0.,  0.,  1.],
       [ 1.,  1.,  0.,  1.],
       [ 1.,  0.,  0.,  1.],
       [ 0.,  0.,  0.,  1.],
       [ 0.,  0.,  0.,  1.],
       [ 0.,  1.,  1.,  1.],
       [ 0.,  1.,  0.,  1.],
       [ 1.,  0.,  1.,  1.],
       [ 0.,  0.,  1.,  1.],
       [ 0.,  0.,  0.,  1.],
       [ 0.,  1.,  1.,  1.],
       [ 0.,  0.,  1.,  1.],
       [ 1.,  0.,  1.,  1.],
       [ 1.,  1.,  1.,  1.],
       [ 1.,  0.,  0.,  1.],
       [ 1.,  1.,  0.,  1.],
       [ 1.,  0.,  0.,  1.],
       [ 1.,  1.,  1.,  1.],
       [ 1.,  0.,  1.,  1.],
       [ 1.,  1.,  1.,  1.],
       [ 1.,  1.,  0.,  1.],
       [ 0.,  1.,  0.,  1.],
       [ 1.,  1.,  1.,  1.],
       [ 0.,  1.,  0.,  1.],
       [ 0.,  1.,  1.,  1.],
       [ 1.,  1.,  1.,  1.],
       [ 0.,  1.,  1.,  1.],
       [ 1.,  0.,  1.,  1.]])


class TrackballCamera(object):
    def __init__(self, position=(0.0, 0.0, 1.0), focus=(0.0, 0.0, 0.0),
                 fov=45.0, near_plane=1.0, far_plane=20.0, aspect_ratio=8.0/6.0):
        self.view_matrix = np.zeros((4, 4), dtype=np.float32)
        self.proj_matrix = np.zeros((4, 4), dtype=np.float32)
        self.position = np.array(position)
        self.focus = np.array(focus)
        self.fov = fov
        self.near_plane = near_plane
        self.far_plane = far_plane
        self.aspect_ratio = aspect_ratio
        self.orientation = np.array([1.0, 0.0, 0.0, 0.0])

    def _map_to_surface(self, mouse_x, mouse_y):
        # right now this just maps to the surface of
        # the unit sphere
        x, y = mouse_x, mouse_y
        mag = np.sqrt(x*x + y*y)
        if (mag > 1.0):
            x /= mag
            y /= mag
            z = 0.0
        else:
            z = np.sqrt(1.0 - mag**2)
        return np.array([x, -y, z])

    def update_orientation(self, start_x, start_y, end_x, end_y):
        old = self._map_to_surface(start_x, start_y)
        new = self._map_to_surface(end_x, end_y)

        # dot product
        w = old[0]*new[0] + old[1]*new[1] + old[2]*new[2]

        # cross product gives the rotation axis
        x = old[1]*new[2] - old[2]*new[1]
        y = old[2]*new[0] - old[0]*new[2]
        z = old[0]*new[1] - old[1]*new[0]

        q = np.array([w, x, y, z])

        #renormalize to prevent floating point issues
        mag = np.sqrt(w**2 + x**2 + y**2 + z**2)
        q /= mag

        self.orientation = quaternion_mult(self.orientation, q)

    def compute_matrices(self):
        rotation_matrix = quaternion_to_rotation_matrix(self.orientation)
        self.position = self.position*rotation_matrix[2]
        up = rotation_matrix[1]

        self.view_matrix = get_lookat_matrix(self.position, self.focus, up)

        self.projection_matrix = get_perspective_matrix(np.radians(self.fov),
                                                        self.aspect_ratio,
                                                        self.near_plane,
                                                        self.far_plane)

    def get_viewpoint(self):
        return self.position

    def get_view_matrix(self):
        return self.view_matrix

    def get_projection_matrix(self):
        return self.projection_matrix


class Camera:
    def __init__(self, position = (0, 0, 0), fov = 60.0, near_plane = 0.01,
            far_plane = 20, aspect_ratio = 8.0 / 6.0, focus = (0, 0, 0),
            up = (0, 0, 1)):
        self.position = np.array(position)
        self.fov = fov
        self.near_plane = near_plane
        self.far_plane = far_plane
        self.aspect_ratio = aspect_ratio
        self.up = np.array(up)
        self.focus = np.array(focus)

    def get_viewpoint(self):
        return position
    def get_view_matrix(self):
        return get_lookat_matrix(self.position, self.focus, self.up)
    def get_projection_matrix(self):
        return get_perspective_matrix(np.radians(self.fov), self.aspect_ratio, self.near_plane,
                self.far_plane)
    def update_position(self, theta, phi):
        rho = np.linalg.norm(self.position)
        curr_theta = np.arctan2( self.position[1], self.position[0] )
        curr_phi = np.arctan2( np.linalg.norm(self.position[:2]), self.position[2])

        curr_theta += theta
        curr_phi += phi

        self.position[0] = rho * np.sin(curr_phi) * np.cos(curr_theta)
        self.position[1] = rho * np.sin(curr_phi) * np.sin(curr_theta)
        self.position[2] = rho * np.cos(curr_phi)

class BlockCollection:
    def __init__(self):
        self.data_source = None

        self.blocks = [] # A collection of PartionedGrid objects

        self.gl_buffer_name = None
        self.gl_texture_names = []
        self.gl_vao_name = None

        self.redraw = True

        self.geometry_loaded = False

        self.camera = None
        GL.glEnable(GL.GL_CULL_FACE)
        GL.glCullFace(GL.GL_BACK)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LESS)

        self._init_blending()

    def _init_blending(self):
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendColor(1.0, 1.0, 1.0, 1.0)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
        GL.glBlendEquation(GL.GL_MAX)

    def add_data(self, data_source, field):
        r"""Adds a source of data for the block collection.

        Given a `data_source` and a `field` to populate from, adds the data
        to the block collection so that is able to be rendered.

        Parameters
        ----------
        data_source : YTRegion
            A YTRegion object to use as a data source.
        field - String
            A field to populate from.

        """
        self.data_source = data_source
        self.data_source.tiles.set_fields([field], [True], True)

    def set_camera(self, camera):
        r"""Sets the camera for the block collection.

        Parameters
        ----------
        camera : Camera
            A simple camera object.

        """
        self.blocks = []
        vert = []
        self.min_val = 1e60
        self.max_val = -1e60
        for block in self.data_source.tiles.traverse(viewpoint = camera.position):
            self.min_val = min(self.min_val, block.my_data[0].min())
            self.max_val = max(self.max_val, block.my_data[0].max())
            self.blocks.append(block)
            vert.append(self._compute_geometry(block, bbox_vertices))
        self.camera = camera

        # Now we set up our buffer
        vert = np.concatenate(vert)
        if self.gl_buffer_name != None:
            GL.glDeleteBuffers(1, [self.gl_buffer_name])
        self.gl_buffer_name = GL.glGenBuffers(1)
        if self.gl_vao_name != None:
            GL.glDeleteVertexArrays(1, [self.gl_vao_name])
        self.gl_vao_name = GL.glGenVertexArrays(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.gl_buffer_name)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, vert.nbytes, vert, GL.GL_STATIC_DRAW)
        redraw = True

    def run_program(self, shader_program):
        r"""Runs a given shader program on the block collection.

        Parameters
        ----------
        shader_program : int
            An integer name for an OpenGL shader program.

        """
        GL.glUseProgram(shader_program)

        GL.glBindVertexArray(self.gl_vao_name)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.gl_buffer_name)

        vert_location = GL.glGetAttribLocation(shader_program, "model_vertex")

        GL.glVertexAttribPointer(vert_location, 4, GL.GL_FLOAT, False, 0, None)
        GL.glEnableVertexAttribArray(vert_location)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

        self._set_uniforms(shader_program)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        self._load_textures()
        dx_loc = GL.glGetUniformLocation(shader_program, "dx")
        left_edge_loc = GL.glGetUniformLocation(shader_program, "left_edge")
        right_edge_loc = GL.glGetUniformLocation(shader_program, "right_edge")
        camera_loc = GL.glGetUniformLocation(shader_program, "camera_pos")
        GL.glUniform3fv(camera_loc, 1, self.camera.position)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.gl_buffer_name)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        for i in range(0, len(self.blocks)):
            self._set_bounds(self.blocks[i], shader_program,
                dx_loc, left_edge_loc, right_edge_loc)
            GL.glBindTexture(GL.GL_TEXTURE_3D, self.gl_texture_names[i])
            GL.glDrawArrays(GL.GL_TRIANGLES, i*36, 36)

        GL.glDisableVertexAttribArray(vert_location)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    def _set_bounds(self, block, shader_program, dx, le, re):
        dds = (block.RightEdge - block.LeftEdge)/block.my_data[0].shape
        GL.glUniform3fv(dx, 1, dds)
        GL.glUniform3fv(le, 1, block.LeftEdge)
        GL.glUniform3fv(re, 1, block.RightEdge)

    def _set_uniforms(self, shader_program):
        project_loc = GL.glGetUniformLocation(shader_program, "projection")
        lookat_loc = GL.glGetUniformLocation(shader_program, "lookat")
        viewport_loc = GL.glGetUniformLocation(shader_program, "viewport")

        project = self.camera.get_projection_matrix()
        view = self.camera.get_view_matrix()

        viewport = np.array(GL.glGetIntegerv(GL.GL_VIEWPORT), dtype = 'float32')

        GL.glUniformMatrix4fv(project_loc, 1, GL.GL_TRUE, project)
        GL.glUniformMatrix4fv(lookat_loc, 1, GL.GL_TRUE, view)
        GL.glUniform4fv(viewport_loc, 1, viewport)

    def _compute_geometry(self, block, bbox_vertices):
        move = get_translate_matrix(*block.LeftEdge)
        dds = (block.RightEdge - block.LeftEdge)
        scale = get_scale_matrix(*dds)

        transformed_box = bbox_vertices.dot(scale.T).dot(move.T).astype("float32")
        return transformed_box

    def _load_textures(self):
        if len(self.gl_texture_names) == 0:
            self.gl_texture_names = GL.glGenTextures(len(self.blocks))
            if len(self.blocks) == 1:
                self.gl_texture_names = [self.gl_texture_names]
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexParameterf(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameterf(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_MIN_FILTER,
                    GL.GL_LINEAR)

        else:
            for texture in self.gl_texture_names:
                GL.glDeleteTextures([texture])

            self.gl_texture_names = GL.glGenTextures(len(self.blocks))
            if len(self.blocks) == 1:
                self.gl_texture_names = [self.gl_texture_names]

        for block, texture_name in zip(self.blocks, self.gl_texture_names):
            dx, dy, dz = block.my_data[0].shape
            n_data = block.my_data[0].copy(order="F").astype("float32")
            n_data = (n_data - self.min_val) / (self.max_val - self.min_val)
            GL.glBindTexture(GL.GL_TEXTURE_3D, texture_name)
            GL.glTexParameterf(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameterf(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameterf(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_WRAP_R, GL.GL_CLAMP_TO_EDGE)
            GL.glTexStorage3D(GL.GL_TEXTURE_3D, 1, GL.GL_R32F,
                *block.my_data[0].shape)
            GL.glTexSubImage3D(GL.GL_TEXTURE_3D, 0, 0, 0, 0, dx, dy, dz,
                        GL.GL_RED, GL.GL_FLOAT, n_data.T)
            GL.glGenerateMipmap(GL.GL_TEXTURE_3D)

class SceneGraph:
    def __init__(self):
        self.collections = []
        self.camera = None

        self.gl_vert_shader = None
        self.gl_frag_shader = None
        self.shader_program = None

        self.camera = None

    def add_collection(self, collection):
        r"""Adds a block collection to the scene. Collections must not overlap.

        Although it hasn't been tested, this should allow one to add multiple
        datasets to a single scene.

        Parameters
        ----------
        collection : BlockCollection
            A block collection object representing a data-set. Behavior is
            undefined if any collection overlaps with another.

        """
        self.collections.append(collection)

    def set_camera(self, camera):
        r""" Sets the camera orientation for the entire scene.

        Upon calling this function a kd-tree is constructed for each collection.
        This function simply calls the BlockCollection set_camera function on
        each collection in the scene.

        Parameters
        ----------
        camera : Camera

        """
        self.camera = camera
        for collection in self.collections:
            collection.set_camera(camera)

    def add_shader_from_file(self, filename):
        r""" Compiles and links a fragment shader.

        Given a `filename`, compiles and links the given fragment shader. This
        function also compiles a fixed vertex shader. This function then attaches
        these shaders to the current scene.

        Parameters
        ----------
        filename : String
            The location of the shader source file to read.

        """
        vr_directory = os.path.dirname(__file__)
        frag_path = "shaders/" + filename
        vert_path = "shaders/vert.glsl"
        frag_abs = os.path.join(vr_directory, frag_path)
        vert_abs = os.path.join(vr_directory, vert_path)

        shader_file = open(frag_abs, 'r')
        self.gl_frag_shader = shaders.compileShader(shader_file.read(), GL.GL_FRAGMENT_SHADER)

        vert_file = open(vert_abs, 'r')
        self.gl_vert_shader = shaders.compileShader(vert_file.read(), GL.GL_VERTEX_SHADER)

        self.shader_program = GL.glCreateProgram()
        GL.glAttachShader(self.shader_program, self.gl_vert_shader)
        GL.glAttachShader(self.shader_program, self.gl_frag_shader)

        GL.glLinkProgram(self.shader_program)

    def render(self):
        """ Renders one frame of the scene.

        Renders the scene using the current collection and camera set by calls
        to add_collection and set_camera respectively. Also uses the last shader
        provided to the add_shader_from_file function.

        """
        for collection in self.collections:
            collection.run_program(self.shader_program)
