"""
This file contains code for automatically generating the functions and jacobians
used when sampling inside the supported finite element mesh types. The supported
mesh types are defined in yt/utilities/mesh_types.yaml.

Usage (from the yt/utilities directory):

python mesh_code_generation.py 

This will generate the necessary functions and write them to 
yt/utilities/lib/autogenerated_element_samplers.pyx.


"""

#-----------------------------------------------------------------------------
# Copyright (c) 2016, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from sympy import \
    symarray, \
    diff, \
    ccode, \
    Matrix, \
    MatrixSymbol
import yaml


# define some templates used below
fun_signature = '''cdef void %s(double* fx,
                       double* x,
                       double* vertices,
                       double* phys_x) nogil'''

fun_dec_template = fun_signature + ' \n'
fun_def_template = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True) \n''' + fun_signature + ': \n'

jac_signature_3D = '''cdef void %s(double* rcol,
                       double* scol,
                       double* tcol,
                       double* x,
                       double* vertices,
                       double* phys_x) nogil'''

jac_dec_template_3D = jac_signature_3D + ' \n'
jac_def_template_3D = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True) \n''' + jac_signature_3D + ': \n'

jac_signature_2D = '''cdef void %s(double* rcol,
                       double* scol,
                       double* x,
                       double* vertices,
                       double* phys_x) nogil'''
jac_dec_template_2D = jac_signature_2D + ' \n'
jac_def_template_2D = '''@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True) \n''' + jac_signature_2D + ': \n'

file_header = "# This file contains auto-generated functions for sampling \n" + \
              "# inside finite element solutions for various mesh types. \n" + \
              "# To see how the code generation works in detail, see \n" + \
              "# yt/utilities/mesh_code_generation.py. \n"


class MeshCodeGenerator:
    '''

    A class for automatically generating the functions and jacobians used for
    sampling inside finite element calculations.

    '''
    def __init__(self, mesh_data):
        '''

        Mesh data should be a dictionary containing information about the type
        of elements used. See yt/utilities/mesh_types.yaml for more information.

        '''
        self.mesh_type = mesh_data['mesh_type']
        self.num_dim = mesh_data['num_dim']
        self.num_vertices = mesh_data['num_vertices']
        self.num_mapped_coords = mesh_data['num_mapped_coords']

        x = MatrixSymbol('x', self.num_mapped_coords, 1)
        self.x = x
        self.N = Matrix(eval(mesh_data['shape_functions']))
        self._compute_jacobian()

    def _compute_jacobian(self):

        assert(self.num_vertices == len(self.N))
        assert(self.num_dim == self.num_mapped_coords)

        X = MatrixSymbol("vertices", self.num_vertices, self.num_dim)
        self.fx = MatrixSymbol("fx", self.num_dim, 1)
        physical_position = MatrixSymbol('phys_x', self.num_dim, 1)

        self.f = (self.N.T * Matrix(X)).T - physical_position

        self.J = symarray('J', (self.num_dim, self.num_dim))
        for i in range(self.num_dim):
            for j, var in enumerate(self.x):
                self.J[i][j] = diff(self.f[i, 0], var)

        self.rcol = MatrixSymbol("rcol", self.num_dim, 1)
        self.scol = MatrixSymbol("scol", self.num_dim, 1)
        self.tcol = MatrixSymbol("tcol", self.num_dim, 1)

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

    def get_interpolator_definition(self):
        '''

        This returns the function definitions for the given mesh type.

        '''

        function_code = self.function_header
        for i in range(self.num_dim):
            function_code += '\t' + ccode(self.f[i, 0], self.fx[i, 0]) + '\n'
    
        jacobian_code = self.jacobian_header
        for i in range(self.num_dim):
            jacobian_code += '\t' + ccode(self.J[i,0], self.rcol[i, 0]) + '\n'
            jacobian_code += '\t' + ccode(self.J[i,1], self.scol[i, 0]) + '\n'
            if self.num_dim == 2: 
                continue
            jacobian_code += '\t' + ccode(self.J[i,2], self.tcol[i, 0]) + '\n'
            
        return function_code, jacobian_code

    def get_interpolator_declaration(self):
        '''

        This returns the function declarations for the given mesh type.

        '''
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
    
    for _, mesh_data in sorted(mesh_types.items()):
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
