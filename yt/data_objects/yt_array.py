"""
YTArray class.

Author: Casey W. Stark <caseywstark@gmail.com>
Affiliation: UC Berkeley
Author: Nathan Goldbaum <goldbaum@ucolick.org>
Affiliartion: UCSC

Homepage: http://yt-project.org/
License:
  Copyright (C) 2013 Casey W. Stark.  All Rights Reserved.

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

import copy

import numpy as np
import sympy

from numpy import add, subtract, multiply, divide, \
    negative, absolute, sqrt, square, power, reciprocal, ones_like, \
    isnan, isinf, cos, sin, log10, greater, equal, not_equal, \
    less_equal, greater_equal, less, \
    bitwise_or, bitwise_not, bitwise_and

from yt.utilities.units import Unit
from yt.utilities.exceptions import YTUnitOperationError, YTUnitConversionError
from numbers import Number as numeric_type

def ensure_unitless(func):
    def wrapped(unit):
        if unit != Unit():
            raise InvalidUnitOperation(
                "Arguments of %s must be unitless" % str(func)
                )
        return func(unit)
            
def ensure_same_units(func):
    def wrapped(unit1, unit2):
        if unit1 != unit2:
            raise InvalidUnitOperation(
                "Arguments of %s must have the same units" % str(func)
                )
        return func(unit1, unit2)

def sqrt_unit(unit):
    return unit**0.5

def multiply_units(unit1, unit2):
    return unit1 * unit2

def preserve_unit(unit1, unit2):
    return unit1

def power_unit(unit, power):
    return unit**power

def square_unit(unit):
    return unit*unit

def divide_units(unit1, unit2):
    return unit1/unit2

def ones_like_units(unit):
    return unit

def isnan_unit(unit):
    return None

def isinf_unit(unit):
    return None

def negative_unit(unit):
    return unit

def absolute_unit(unit):
    return unit

@ensure_unitless
def cos_unit(unit):
    return Unit()

@ensure_unitless
def sin_unit(unit):
    return Unit()

@ensure_unitless
def log10_unit(unit):
    return Unit()

def greater_unit(unit1, unit2):
    return None

def less_unit(unit1, unit2):
    return None

def greater_equal_unit(unit1, unit2):
    return None

def less_equal_unit(unit1, unit2):
    return None

def equal_unit(unit1, unit2):
    return None

def not_equal_unit(unit1, unit2):
    return None

@ensure_same_units
def bitwise_and_unit(unit1, unit2):
    return unit1

@ensure_same_units
def bitwise_or_unit(unit1, unit2):
    return unit1

@ensure_same_units
def bitwise_not_unit(unit1, unit2):
    return unit1

class YTArray(np.ndarray):
    """

    """
    _ufunc_registry = {sqrt: sqrt_unit, multiply: multiply_units,
                       add: preserve_unit, subtract: preserve_unit,
                       power: power_unit, divide: divide_units,
                       square: square_unit, ones_like: ones_like_units,
                       isnan: isnan_unit, isinf: isinf_unit,
                       negative: negative_unit, absolute: absolute_unit,
                       cos: cos_unit, sin: sin_unit, log10: log10_unit, equal:
                       equal_unit, greater: greater_unit, greater_equal:
                       greater_equal_unit, less: less_unit, less_equal:
                       less_equal_unit, not_equal: not_equal_unit, bitwise_or:
                       bitwise_or_unit, bitwise_not: bitwise_not_unit,
                       bitwise_and: bitwise_and_unit}

    def __new__(cls, input_array, input_units=None, registry=None):
        if isinstance(input_array, YTArray):
            return input_array

        # Input array is an already formed ndarray instance
        # We first cast to be our class type
        obj = np.asarray(input_array).view(cls)

        # Check units type
        if input_units is None:
            # Nothing provided. Make dimensionless...
            units = Unit()
        elif isinstance(input_units, Unit):
            units = input_units
        else:
            # units kwarg set, but it's not a Unit object.
            # don't handle all the cases here, let the Unit class handle if
            # it's a str.
            units = Unit(input_units, registry=registry)

        # Attach the units
        obj.units = units

        return obj

    def __array_finalize__(self, obj):
        """

        """
        if obj is None:
            return
        self.units = getattr(obj, 'units', None)

    def __repr__(self):
        """

        """
        return super(YTArray, self).__repr__()+' '+self.units.__repr__()

    def __str__(self):
        """

        """
        return super(YTArray, self).__str__()+' '+self.units.__str__()

    #
    # Start unit conversion methods
    #

    def _unit_repr_check_same(self, units):
        """
        Takes a Unit object, or string of known unit symbol, and check that it
        is compatible with this quantity. Returns Unit object.

        """
        # let Unit() handle units arg if it's not already a Unit obj.
        if not isinstance(units, Unit):
            units = Unit(units)

        if not self.units.same_dimensions_as(units):
            raise YTUnitConversionError(
                self.units, self.units.dimensions, units, units.dimensions)

        return units

    def convert_to_units(self, units):
        """
        Convert the array and units to the given units.

        Parameters
        ----------
        units : Unit object or str
            The units you want to convert to.

        """
        new_units = self._unit_repr_check_same(units)
        conversion_factor = self.units.get_conversion_factor(new_units)

        self *= conversion_factor
        self.units = new_units

    def convert_to_cgs(self):
        """
        Convert the array and units to the equivalent cgs units.

        """
        return self.convert_to_units(self.units.get_cgs_equivalent())

    def in_units(self, units):
        """
        Creates a copy of this array with the data in the supplied units, and
        returns it.

        Parameters
        ----------
        units : Unit object or string
            The units you want to get a new quantity in.

        Returns
        -------
        YTArray

        """
        new_units = self._unit_repr_check_same(units)
        conversion_factor = self.units.get_conversion_factor(new_units)

        new_array = self * conversion_factor
        new_array.units = new_units

        return new_array

    def in_cgs(self):
        """
        Creates a copy of this array with the data in the equivalent cgs units,
        and returns it.

        Returns
        -------
        Quantity object with data converted to cgs and cgs units.

        """
        return self.in_units(self.units.get_cgs_equivalent())

    #
    # End unit conversion methods
    #

    #
    # Start operation methods
    #

    def __add__(self, right_object):
        """
        Add this ytarray to the object on the right of the `+` operator. Must
        check for the correct (same dimension) units.

        """
        # Make sure the other object is a YTArray before we use the `units`
        # attribute.
        if isinstance(right_object, YTArray):
            if not self.units.same_dimensions_as(right_object.units):
                raise YTUnitOperationError('addition', self.units,
                                           right_object.units)
        # If the other object is not a YTArray, the only valid case is adding
        # dimensionless things.
        else:
            if not self.units.is_dimensionless:
                raise YTUnitOperationError('addition', self.units,
                                           right_object.units)

        return YTArray(super(YTArray, self).__add__(right_object))

    def __radd__(self, left_object):
        """ See __add__. """
        if isinstance(left_object, YTArray):
            if not self.units.same_dimensions_as(left_object.units):
                raise YTUnitOperationError('addition', left_object.units,
                                           self.units)
        else:
            if not self.units.is_dimensionless:
                raise YTUnitOperationError('addition', left_object.units,
                                           self.units)

        return YTArray(super(YTArray, self).__radd__(left_object))

    def __iadd__(self, other):
        """ See __add__. """
        return np.add(self, other, out=self)

    def __sub__(self, right_object):
        """
        Subtract the object on the right of the `-` from this ytarray. Must
        check for the correct (same dimension) units.

        """
        # Make sure the other object is a YTArray before we use the `units`
        # attribute.
        if isinstance(right_object, YTArray):
            if not self.units.same_dimensions_as(right_object.units):
                raise YTUnitOperationError('subtraction', self.units,
                                           right_object.units)
        # If the other object is not a YTArray, the only valid case is adding
        # dimensionless things.
        else:
            if not self.units.is_dimensionless:
                raise YTUnitOperationError('subtraction', self.units,
                                           right_object.units)

        return YTArray(super(YTArray, self).__sub__(right_object))

    def __rsub__(self, left_object):
        """ See __sub__. """
        if isinstance(left_object, YTArray):
                raise YTUnitOperationError('subtraction', left_object.units,
                                           self.units)
        else:
                raise YTUnitOperationError('subtraction', left_object.units,
                                           self.units)

        return YTArray(super(YTArray, self).__rsub__(left_object))

    def __isub__(self, other):
        """ See __sub__. """
        return np.subtract(self, other, out=self)

    def __neg__(self):
        """ Negate the data. """
        return YTArray(super(YTArray, self).__neg__())

    def __mul__(self, right_object):
        """
        Multiply this YTArray by the object on the right of the `*` operator.
        The unit objects handle being multiplied.

        """
        return YTArray(super(YTArray, self).__mul__(right_object))

    def __rmul__(self, left_object):
        """ See __mul__. """
        return YTArray(super(YTArray, self).__rmul__(left_object))

    def __imul__(self, other):
        """ See __mul__. """
        return np.multiply(self, other, out=self)

    def __div__(self, right_object):
        """
        Divide this YTArray by the object on the right of the `/` operator.

        """
        return YTArray(super(YTArray, self).__div__(right_object))

    def __rdiv__(self, left_object):
        """ See __div__. """
        return YTArray(super(YTArray, self).__rdiv__(left_object))

    def __idiv__(self, other):
        """ See __div__. """
        return np.divide(self, other, out=self)

    def __truediv__(self, right_object):
        return YTArray(super(YTArray, self).__truediv__(right_object))

    def __rtruediv__(self, left_object):
        """ See __div__. """
        return YTArray(super(YTArray, self).__rtruediv__(left_object))

    def __itruediv__(self, other):
        """ See __div__. """
        return np.true_divide(self, other, out=self)

    def __floordiv__(self, right_object):
        return YTArray(super(YTArray, self).__floordiv__(right_object))

    def __rfloordiv__(self, left_object):
        """ See __div__. """
        return YTArray(super(YTArray, self).__rfloordiv__(left_object))

    def __ifloordiv__(self, other):
        """ See __div__. """
        return np.floor_divide(self, other, out=self)
    
    #Should these raise errors?  I need to come back and check this.
    def __or__(self, right_object):
        return YTArray(super(YTArray, self).__or__(right_object))

    def __ror__(self, left_object):
        return YTArray(super(YTArray, self).__ror__(left_object))

    def __ior__(self, other):
        return np.bitwise_or(self, other, out=self)

    def __xor__(self, right_object):
        return YTArray(super(YTArray, self).__xor__(right_object))

    def __rxor__(self, left_object):
        return YTArray(super(YTArray, self).__rxor__(left_object))

    def __ixor__(self, other):
        return np.bitwise_xor(self, other, out=self)

    def __and__(self, right_object):
        return YTArray(super(YTArray, self).__and__(right_object))

    def __rand__(self, left_object):
        return YTArray(super(YTArray, self).__rand__(left_object))

    def __iand__(self, other):
        return np.bitwise_and(self, other, out=self)

    def __pow__(self, power):
        """
        Raise this YTArray to some power.

        Parameters
        ----------
        power : float or dimensionless YTArray.
            The pow value.

        """
        if isinstance(power, YTArray):
            if not power.units.is_dimensionless:
                raise YTUnitOperationError('power', power.unit)

        return YTArray(super(YTArray, self).__pow__(power))
    
    def __abs__(self):
        """ Return a YTArray with the abs of the data. """
        return YTArray(super(YTArray, self).__abs__())

    def sqrt(self):
        """
        Return sqrt of this YTArray. We take the sqrt for the array and use
        take the 1/2 power of the units.

        """
        return YTArray(super(YTArray, self).sqrt(),
                       input_units=self.units**0.5)

    #
    # Start comparison operators.
    #

    # @todo: outsource to a single method with an op argument.
    def __lt__(self, other):
        """ Test if this is less than the object on the right. """
        # Check that other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError('less than', self.units, other.units)

            return np.array(self).__lt__(np.array(other.in_units(self.units)))

        return np.array(self).__lt__(np.array(other))

    def __le__(self, other):
        """ Test if this is less than or equal to the object on the right. """
        # Check that other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError('less than or equal', self.units, other.units)

            return np.array(self).__le__(np.array(other.in_units(self.units)))

        return np.array(self).__le__(np.array(other))

    def __eq__(self, other):
        """ Test if this is equal to the object on the right. """
        # Check that other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("equal", self.units, other.units)

            return np.array(self).__eq__(np.array(other.in_units(self.units)))

        return np.array(self).__eq__(np.array(other))

    def __ne__(self, other):
        """ Test if this is not equal to the object on the right. """
        # Check that the other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("not equal", self.units, other.units)

            return np.array(self).__ne__(np.array(other.in_units(self.units)))

        return np.array(self).__ne__(np.array(other))

    def __ge__(self, other):
        """ Test if this is greater than or equal to other. """
        # Check that the other is a YTArray.
        if isinstance(right_object, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("greater than or equal", self.units, other.units)

            return np.array(self).__ge__(np.array(other.in_units(self.units)))

        return np.array(self).__ge__(np.array(other))

    def __gt__(self, other):
        """ Test if this is greater than the object on the right. """
        # Check that the other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("greater than", self.units, other.units)

            return np.array(self).__gt__(np.array(other.in_units(self.units)))

        return np.array(self).__gt__(np.array(other))

    #
    # End comparison operators
    #

    def __array_wrap__(self, out_arr, context=None):
        if context is None:
            pass
        elif len(context[1]) == 1:
            # unary operators
            unit = self._ufunc_registry[context[0]](context[1][0].units)
            if unit is None:
                out_arr = np.array(out_arr)
            else:
                out_arr.units = unit
        elif len(context[1]) == 2:
            # binary operators
            try:
                unit1 = context[1][0].units
            except AttributeError:
                unit1 = Unit()
            try:
                unit2 = context[1][1].units
            except AttributeError:
                if context[0] is power:
                    unit2 = context[1][1]
                else:
                    unit2 = Unit()
            unit = self._ufunc_registry[context[0]](unit1, unit2)
            if unit is None:
                out_arr = np.array(out_arr)
            else:
                out_arr.units = unit
        else:
            raise RuntimeError("Only unary and binary operators are allowed.")
        if out_arr.size == 1 and out_arr.size != self.size:
            return out_arr[0]
        return super(YTArray, self).__array_wrap__(out_arr, context)

class YTQuantity(YTArray):
    def __new__(cls, input, input_units=None, registry=None):
        if not isinstance(input, numeric_type):
            raise RuntimeError('Quantity values must be numeric')
        return YTArray.__new__(cls, input, input_units, registry)
