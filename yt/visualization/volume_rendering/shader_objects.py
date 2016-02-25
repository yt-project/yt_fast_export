import OpenGL as GL

class ShaderProgram(object):
    def __init__(self, vertex_shader = None, fragment_shader = None):
        # Don't allow just one.  Either neither or both.
        if vertex_shader is None and fragment_shader is None:
            pass
        elif None not in (vertex_shader, fragment_shader):
            self.link(vertex_shader, fragment_shader)
        else:
            raise RuntimeError

    def link(self, vertex_shader, fragment_shader):
        # There are more types of shaders, but for now we only allow v&f.
        self.program = GL.glCreateProgram()
        if not isinstance(vertex_shader, VertexShader):
            vertex_shader = VertexShader(vertex_shader)
        if not isinstance(fragment_shader, FragmentShader):
            fragment_shader = FragmentShader(fragment_shader)
        self.vertex_shader = vertex_shader
        self.fragment_shader = fragment_shader
        GL.glAttachShader(self.program, vertex_shader)
        GL.glAttachShader(self.program, fragment_shader)
        GL.glLinkProgram(self.program)
        result = GL.glGetProgramiv(self.program, GL.GL_LINK_STATUS)
        if not result:
            raise RuntimeError(GL.glGetProgramInfoLog(self.program))

    def _guess_uniform_func(self, value):
        # We make a best-effort guess.
        # This does NOT work with arrays of uniforms.
        # First look at the dtype kind.  Fortunately, this falls into either
        # 'f' or 'i', which matches nicely with OpenGL.
        # Note that in some implementations, it seems there is also a 'd' type,
        # but we will not be using that here.
        kind = value.dtype.kind
        if kind not in 'if':
            raise YTUnknownUniformKind(kind)
        if len(value.shape) == 1:
            if value.size > 4:
                raise YTUnknownUniformSize(value.size)
            func = self._set_scalar_uniform(kind, value.size)
        elif len(value.shape) == 2:
            if value.shape[0] != value.shape[1]:
                raise YTUnknownUniformSize(value.shape)
            func = self._set_matrix_uniform(kind, value.shape)
        else:
            raise YTUnknownUniformSize(value.shape)
        return func

    def _set_scalar_uniform(self, kind, size_spec):
        gl_func = getattr(GL, "glUniform%s%sv" % (size_spec, kind))
        def _func(location, value):
            return gl_func(location, 1, value)
        return _func

    def _set_matrix_uniform(self, kind, size_spec):
        assert(size_spec[0] == size_spec[1])
        gl_func = getattr(GL, "glUniformMatrix%s%sv" % (size_spec[0], kind))
        def _func(location, value):
            return gl_func(location, 1, GL.GL_TRUE, value)
        return _func

    def _set_uniform(self, name, value):
        # We need to figure out how to pass it in.
        if name not in self._uniform_funcs:
            self._uniform_funcs[name] = self._guess_uniform_func(value)
        loc = GL.glGetUniformLocation(self.program, name)
        return self._uniform_funcs[name](loc, value)

    @contextlib.contextmanager
    def enable(self):
        GL.glUseProgram(self.program)
        yield
        GL.glUseProgram(0)

    def bind_vert_attrib(self, name):
        bind_loc, size = self.vert_attrib[name]
        loc = GL.glGetAttribLocation(self.program, name)
        GL.glEnableVertexAttribArray(loc)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, bind_loc)
        GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, False, 0, None)

    def disable_vert_attrib(self, name):
        loc = GL.glGetAttribLocation(self.program, name)
        GL.glDisableVertexAttribArray(loc)


class Shader(object):
    shader = None
    _source = None
    def __init__(self, source = None):
        if source:
            self.compile(source)

    def _get_source(self, source):
        if ";" in source:
            # This is probably safe, right?  Enh, probably.
            return source
        if os.path.isfile(source):
            sh_directory = ''
        else:
            sh_directory = os.path.join(os.path.dirname(__file__), "shaders")
        fn = os.path.join(sh_directory, source)
        if not os.path.isfile(fn):
            raise YTInvalidShaderType(source)
        return open(fn, 'r').read()

    def compile(self, source = None, parameters = None):
        if source is None:
            source = self._source
            if source is None: raise RuntimeError
        if parameters is not None:
            raise NotImplementedError
        source = self._get_source(source)
        shader_type_enum = getattr(GL,
            'GL_%s_SHADER' % self.shader_type.upper())
        shader = GL.glCreateShader(shader_type_enum)
        # We could do templating here if we wanted.
        self.shader_source = source
        GL.glShaderSource(shader, source)
        GL.glCompileShader(shader)
        result = GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS)
        if not(result):
            raise RuntimeError(GL.glGetShaderInfoLog(shader))
        self.shader = shader

    def __del__(self):
        # This is not guaranteed to be called
        if self.shader is not None:
            GL.glDeleteShader(self.shader)

class FragmentShader(Shader):
    shader_type = "fragment"

class VertexShader(Shader):
    shader_type = "vertex"

class ApplyColormapFragmentShader(FragmentShader):
    _source = "apply_colormap.fragmentshader"

class MaxIntensityFragmentShader(FragmentShader):
    _source = "max_intensity.fragmentshader"

class NoOpFragmentShader(FragmentShader):
    _source = "noop.fragmentshader"

class PassthroughFragmentShader(FragmentShader):
    _source = "passthrough.fragmentshader"

class ProjectionFragmentShader(FragmentShader):
    _source = "projection.fragmentshader"

class TransferFunctionFragmentShader(FragmentShader):
    _source = "transfer_function.fragmentshader"

class DefaultVertexShader(VertexShader):
    _source = "default.vertexshader"

class PassthroughVertexShader(VertexShader):
    _source = "passthrough.vertexshader"
