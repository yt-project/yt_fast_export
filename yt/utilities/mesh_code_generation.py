from sympy import \
    symarray, \
    symbols, \
    diff
import re
import yaml


fun_dec_template = '''cdef inline void %s(double* fx,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil \n'''

fun_def_template = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef inline void %s(double* fx,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil: \n'''

jac_dec_template_3D = '''cdef inline void %s(double* rcol,
                              double* scol,
                              double* tcol,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil \n'''

jac_def_template_3D = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef inline void %s(double* rcol,
                              double* scol,
                              double* tcol,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil: \n'''

jac_dec_template_2D = '''cdef inline void %s(double* A,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil \n'''

jac_def_template_2D = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef inline void %s(double* A,
                              double* x,
                              double* vertices,
                              double* phys_x) nogil: \n'''

file_header = "# This file contains auto-generated functions for sampling \n" + \
              "# inside finite element solutions for various mesh types."


class MeshCodeGenerator:
    def __init__(self, mesh_data):
        self.mesh_type = mesh_data['mesh_type']
        self.num_dim = mesh_data['num_dim']
        self.num_vertices = mesh_data['num_vertices']
        self.num_mapped_coords = mesh_data['num_mapped_coords']

        x = symarray('x', self.num_mapped_coords)
        self.x = x
        self.N = eval(mesh_data['shape_functions'])
        self._compute_jacobian()

    def _compute_jacobian(self):

        assert(self.num_vertices == len(self.N))
        assert(self.num_dim == self.num_mapped_coords)

        X = symarray('vertices', (self.num_dim, self.num_vertices))
        physical_position = symbols(['phys_x[%s] ' % d for d in '012'[:self.num_dim]])

        self.f = X.dot(self.N) - physical_position

        self.J = symarray('J', (self.num_dim, self.num_dim))
        for i in range(self.num_dim):
            for j, var in enumerate(self.x):
                self.J[i][j] = diff(self.f[i], var)

        self.function_name = '%sFunction%dD' % (self.mesh_type, self.num_dim)
        self.function_header = fun_def_template % self.function_name
        self.function_declaration = fun_dec_template % self.function_name

        self.jacobian_name = '%sJacobian%dD' % (self.mesh_type, self.num_dim)
        if (self.num_dim == 3):
            self.jacobian_header = jac_def_template_3D % self.jacobian_name 
            self.jacobian_declaration = jac_dec_template_3D % self.jacobian_name
        elif (self.num_dim == 2):
            self.jacobian_header = jac_def_template_2D % self.jacobian_name
            self.jacobian_declaration = jac_dec_template_2D % self.jacobian_name            

    def replace_func(self, match):
        s = match.group(0)
        i = int(s[-3])
        j = int(s[-1])
        n = self.num_dim*j + i
        return 'vertices[%d]' % n

    def get_function_line(self, i):
        line = str(self.f[i])
        for j in range(self.num_dim):
            line = re.sub(r'x_%d' % j, 'x[%d]' % j, line)
        line = re.sub(r'(vertices_._.)', self.replace_func, line)
        return '''    fx[%d] =  %s \n''' % (i, line)

    def get_jacobian_line(self, i, j):
        line = str(self.J[i, j])
        for k in range(self.num_dim):
            line = re.sub(r'x_%d' % k, 'x[%d]' % k, line)
        line = re.sub(r'(vertices_._.)', self.replace_func, line)
        if (self.num_dim == 2):
            return '''    A[%d] =  %s \n''' % (2*i + j, line)
        else:
            assert(self.num_dim == 3)
            col = 'rst'[j]
            return '''    %scol[%d] =  %s \n''' % (col, i, line)

    def get_interpolator_definition(self):
        function_code = self.function_header
        for i in range(self.num_mapped_coords):
            function_code += self.get_function_line(i)  
        
        jacobian_code = self.jacobian_header
        for i in range(self.num_dim):
            for j in range(self.num_dim):
                jacobian_code += self.get_jacobian_line(i, j)   
            
        return function_code, jacobian_code

    def get_interpolator_declaration(self):
        return self.function_declaration, self.jacobian_declaration


if __name__ == "__main__":

    with open('mesh_types.yaml', 'r') as f:
        lines = f.read()

    mesh_types = yaml.load(lines)

    pxd_file = open("lib/autogenerated_element_samplers.pxd", "w")
    pyx_file = open("lib/autogenerated_element_samplers.pyx", "w")

    pyx_file.write(file_header)
    pyx_file.write("\n \n")
    pyx_file.write("cimport cython \n \n")
    pyx_file.write("\n \n")
    
    for mesh_data in mesh_types.values():
        codegen = MeshCodeGenerator(mesh_data)

        function_code, jacobian_code = codegen.get_interpolator_definition()
        function_decl, jacobian_decl = codegen.get_interpolator_declaration()

        pxd_file.write(function_decl)
        pxd_file.write("\n \n")
        pxd_file.write(jacobian_decl)
        pxd_file.write("\n \n")

        pyx_file.write(function_code)
        pyx_file.write("\n \n")
        pyx_file.write(jacobian_code)
        pyx_file.write("\n \n")

    pxd_file.close()
    pyx_file.close()
