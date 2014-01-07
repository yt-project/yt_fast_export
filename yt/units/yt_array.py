"""
YTArray class.



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import copy

import numpy as np
import sympy

from numpy import \
     add, subtract, multiply, divide, logaddexp, logaddexp2, true_divide, \
     floor_divide, negative, power, remainder, mod, fmod, absolute, rint, \
     sign, conj, exp, exp2, log, log2, log10, expm1, log1p, sqrt, square, \
     reciprocal, ones_like, sin, cos, tan, arcsin, arccos, arctan, arctan2, \
     hypot, sinh, cosh, tanh, arcsinh, arccosh, arctanh, deg2rad, rad2deg, \
     bitwise_and, bitwise_or, bitwise_xor, invert, left_shift, right_shift, \
     greater, greater_equal, less, less_equal, not_equal, equal, logical_and, \
     logical_or, logical_xor, logical_not, maximum, minimum, isreal, \
     iscomplex, isfinite, isinf, isnan, signbit, copysign, nextafter, modf, \
     ldexp, frexp, fmod, floor, ceil, trunc


from yt.units.unit_object import Unit
from yt.units.unit_registry import UnitRegistry
from yt.units.dimensions import dimensionless
from yt.utilities.exceptions import YTUnitOperationError, YTUnitConversionError
from numbers import Number as numeric_type

# redefine this here to avoid a circular import from yt.funcs
def iterable(obj):
    try: len(obj)
    except: return False
    return True

def ensure_unitless(func):
    def wrapped(unit):
        if unit != Unit():
            raise RuntimeError(
                "This operation is only defined for unitless quantities. " \
                "Received unit (%s)" % unit
                )
        return func(unit)
    return wrapped

def ensure_same_units(func):
    def wrapped(unit1, unit2):
        if None in (unit1, unit2):
            if unit1 is not None and not unit1.is_dimensionless:
                raise RuntimeError("(%s) and (%s) do not match"\
                              % unit1, unit2)
            if unit2 is not None and not unit2.is_dimensionless:
                raise RuntimeError("(%s) and (%s) do not match"\
                              % unit1, unit2)
        elif unit1.dimensions != unit2.dimensions:
            raise RuntimeError("(%s) and (%s) must be equivalent units" \
                               % unit1, unit2)
        return func(unit1, unit2)
    return wrapped

def sqrt_unit(unit):
    return unit**0.5

def multiply_units(unit1, unit2):
    return unit1 * unit2

@ensure_same_units
def preserve_units(unit1, unit2):
    return unit1

def power_unit(unit, power):
    return unit**power

def square_unit(unit):
    return unit*unit

def divide_units(unit1, unit2):
    return unit1/unit2

def reciprocal_unit(unit):
    return 1/unit

def passthrough_unit(unit):
    return unit

def return_without_unit(unit):
    return None

@ensure_unitless
def unitless(unit):
    return Unit()

def sign_unit(unit):
    return Unit()

@ensure_same_units
def arctan2_unit(unit1, unit2):
    return Unit()

@ensure_same_units
def comparison_unit(unit1, unit2):
    return None

@ensure_same_units
def bitwise_comparison_unit(unit1, unit2):
    return unit1

def sanitize_units_mul(this_object, other_object):
    ret = other_object
    # If the other object is a YTArray and has the same dimensions as the object
    # under consideration, convert so we don't mix units with the same
    # dimensions.
    if isinstance(other_object, YTArray):
        if this_object.units.same_dimensions_as(other_object.units):
            ret = other_object.in_units(this_object.units)
    return ret

def sanitize_units_add(this_object, other_object, op_string):
    # Make sure the other object is a YTArray before we use the `units`
    # attribute.
    if isinstance(other_object, YTArray):
        if not this_object.units.same_dimensions_as(other_object.units):
            raise YTUnitOperationError(op_string, this_object.units,
                                       other_object.units)
        ret = other_object.in_units(this_object.units)
    # If the other object is not a YTArray, the only valid case is adding
    # dimensionless things.
    else:
        if not this_object.units.is_dimensionless:
            raise YTUnitOperationError(op_string, this_object.units,
                                       dimensionless)
        ret = other_object
    return ret

class YTArray(np.ndarray):
    """

    """
    _ufunc_registry = {
        add: preserve_units,
        subtract: preserve_units,
        multiply: multiply_units,
        divide: divide_units,
        logaddexp: unitless,
        logaddexp2: unitless,
        true_divide: divide_units,
        floor_divide: divide_units,
        negative: passthrough_unit,
        power: power_unit,
        remainder: preserve_units,
        mod: preserve_units,
        fmod: preserve_units,
        absolute: passthrough_unit,
        rint: passthrough_unit,
        sign: sign_unit,
        conj: passthrough_unit,
        exp: unitless,
        exp2: unitless,
        log: unitless,
        log2: unitless,
        log10: unitless,
        expm1: unitless,
        log1p: unitless,
        sqrt: sqrt_unit,
        square: square_unit,
        reciprocal: reciprocal_unit,
        ones_like: passthrough_unit,
        sin: unitless,
        cos: unitless,
        tan: unitless,
        arcsin: unitless,
        arccos: unitless,
        arctan: unitless,
        arctan2: arctan2_unit,
        hypot: preserve_units,
        deg2rad: unitless,
        rad2deg: unitless,
        bitwise_and: bitwise_comparison_unit,
        bitwise_or: bitwise_comparison_unit,
        bitwise_xor: bitwise_comparison_unit,
        invert: bitwise_comparison_unit,
        left_shift: passthrough_unit,
        right_shift: passthrough_unit,
        greater: comparison_unit,
        greater_equal: comparison_unit,
        less: comparison_unit,
        less_equal: comparison_unit,
        not_equal: comparison_unit,
        equal: comparison_unit,
        logical_and: ensure_same_units,
        logical_or: ensure_same_units,
        logical_xor: ensure_same_units,
        logical_not: ensure_same_units,
        maximum: passthrough_unit,
        minimum: passthrough_unit,
        isreal: return_without_unit,
        iscomplex: return_without_unit,
        isfinite: return_without_unit,
        isinf: return_without_unit,
        isnan: return_without_unit,
        signbit: return_without_unit,
        copysign: preserve_units,
        nextafter: preserve_units,
        modf: passthrough_unit,
        floor: passthrough_unit,
        ceil: passthrough_unit,
        trunc: passthrough_unit
        }

    __array_priority__ = 2.0

    def __new__(cls, input_array, input_units=None, registry=None, dtype=None):
        if input_array is NotImplemented:
            return input_array
        if isinstance(input_array, YTArray):
            if input_units is None:
                pass
            elif isinstance(input_units, Unit):
                input_array.units = input_units
            else:
                input_array.units = Unit(input_units, registry=registry)
            return input_array
        elif isinstance(input_array, np.ndarray):
            pass
        elif iterable(input_array):
            if isinstance(input_array[0], YTQuantity):
                return YTArray(np.array(input_array, dtype=dtype),
                               input_array[0].units)

        # Input array is an already formed ndarray instance
        # We first cast to be our class type

        obj = np.asarray(input_array, dtype=dtype).view(cls)

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
        if obj is None and hasattr(self, 'units'):
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
            units = Unit(units, registry = self.units.registry)

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
        return self

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

    def ndarray_view(self):
        """
        Returns a view into the array, but as an ndarray rather than ytarray.

        Returns
        -------
        View of this array's data.
        """
        return self.view(np.ndarray)

    def to_ndarray(self):
        """
        Creates a copy of this array with the unit information stripped

        """
        return np.array(self)
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
        ro = sanitize_units_add(self, right_object, "addition")
        return YTArray(super(YTArray, self).__add__(ro))

    def __radd__(self, left_object):
        """ See __add__. """
        lo = sanitize_units_add(self, left_object, "addition")
        return YTArray(super(YTArray, self).__radd__(lo))

    def __iadd__(self, other):
        """ See __add__. """
        oth = sanitize_units_add(self, other, "addition")
        return np.add(self, oth, out=self)

    def __sub__(self, right_object):
        """
        Subtract the object on the right of the `-` from this ytarray. Must
        check for the correct (same dimension) units.

        """
        ro = sanitize_units_add(self, right_object, "subtraction")
        return YTArray(super(YTArray, self).__sub__(ro))

    def __rsub__(self, left_object):
        """ See __sub__. """
        lo = sanitize_units_add(self, left_object, "subtraction")
        return YTArray(super(YTArray, self).__rsub__(lo))

    def __isub__(self, other):
        """ See __sub__. """
        oth = sanitize_units_add(self, other, "subtraction")
        return np.subtract(self, other, out=self)

    def __neg__(self):
        """ Negate the data. """
        return YTArray(super(YTArray, self).__neg__())

    def __mul__(self, right_object):
        """
        Multiply this YTArray by the object on the right of the `*` operator.
        The unit objects handle being multiplied.

        """
        ro = sanitize_units_mul(self, right_object)
        return YTArray(super(YTArray, self).__mul__(ro))

    def __rmul__(self, left_object):
        """ See __mul__. """
        lo = sanitize_units_mul(self, left_object)
        return YTArray(super(YTArray, self).__rmul__(lo))

    def __imul__(self, other):
        """ See __mul__. """
        oth = sanitize_units_mul(self, other)
        return np.multiply(self, oth, out=self)

    def __div__(self, right_object):
        """
        Divide this YTArray by the object on the right of the `/` operator.

        """
        ro = sanitize_units_mul(self, right_object)
        return YTArray(super(YTArray, self).__div__(ro))

    def __rdiv__(self, left_object):
        """ See __div__. """
        lo = sanitize_units_mul(self, left_object)
        return YTArray(super(YTArray, self).__rdiv__(lo))

    def __idiv__(self, other):
        """ See __div__. """
        oth = sanitize_units_mul(self, other)
        return np.divide(self, oth, out=self)

    def __truediv__(self, right_object):
        ro = sanitize_units_mul(self, right_object)
        return YTArray(super(YTArray, self).__truediv__(ro))

    def __rtruediv__(self, left_object):
        """ See __div__. """
        lo = sanitize_units_mul(self, left_object)
        return YTArray(super(YTArray, self).__rtruediv__(lo))

    def __itruediv__(self, other):
        """ See __div__. """
        oth = sanitize_units_mul(self, other)
        return np.true_divide(self, oth, out=self)

    def __floordiv__(self, right_object):
        ro = sanitize_units_mul(self, right_object)
        return YTArray(super(YTArray, self).__floordiv__(ro))

    def __rfloordiv__(self, left_object):
        """ See __div__. """
        lo = sanitize_units_mul(self, left_object)
        return YTArray(super(YTArray, self).__rfloordiv__(lo))

    def __ifloordiv__(self, other):
        """ See __div__. """
        oth = sanitize_units_mul(self, other)
        return np.floor_divide(self, oth, out=self)

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
                raise YTUnitOperationError('less than or equal', self.units,
                                           other.units)

            return np.array(self).__le__(np.array(other.in_units(self.units)))

        return np.array(self).__le__(np.array(other))

    def __eq__(self, other):
        """ Test if this is equal to the object on the right. """
        # Check that other is a YTArray.
        if other == None:
            # self is a YTArray, so it can't be None.
            return False
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("equal", self.units, other.units)

            return np.array(self).__eq__(np.array(other.in_units(self.units)))

        return np.array(self).__eq__(np.array(other))

    def __ne__(self, other):
        """ Test if this is not equal to the object on the right. """
        # Check that the other is a YTArray.
        if other == None:
            return True
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("not equal", self.units, other.units)

            return np.array(self).__ne__(np.array(other.in_units(self.units)))

        return np.array(self).__ne__(np.array(other))

    def __ge__(self, other):
        """ Test if this is greater than or equal to other. """
        # Check that the other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("greater than or equal",
                                           self.units, other.units)

            return np.array(self).__ge__(np.array(other.in_units(self.units)))

        return np.array(self).__ge__(np.array(other))

    def __gt__(self, other):
        """ Test if this is greater than the object on the right. """
        # Check that the other is a YTArray.
        if isinstance(other, YTArray):
            if not self.units.same_dimensions_as(other.units):
                raise YTUnitOperationError("greater than", self.units,
                                           other.units)

            return np.array(self).__gt__(np.array(other.in_units(self.units)))

        return np.array(self).__gt__(np.array(other))

    #
    # End comparison operators
    #

    #
    # Begin reduction operators
    #

    def prod(self, axis=None, dtype=None, out=None):
        ret = super(YTArray, self).prod(axis, dtype, out)
        if axis:
            ret = YTArray(ret, self.units**(self.shape[axis]))
        else:
            ret = YTArray(ret, self.units**(self.size))
        return ret

    def mean(self, axis=None, dtype=None, out=None):
        ret = super(YTArray, self).mean(axis, dtype, out)
        return YTArray(ret, self.units)

    def sum(self, axis=None, dtype=None, out=None):
        ret = super(YTArray, self).sum(axis, dtype, out)
        return YTArray(ret, self.units)

    def dot(self, b, out=None):
        ret = super(YTArray, self).dot(b)
        return YTArray(ret, self.units*b.units)

    def std(self, axis=None, dtype=None, out=None, ddof=0):
        ret = super(YTArray, self).std(axis, dtype, out, ddof)
        return YTArray(ret, self.units)

    def __getitem__(self, item):
        ret = super(YTArray, self).__getitem__(item)
        if ret.shape == ():
            return YTQuantity(ret, self.units)
        else:
            return ret

    def __array_wrap__(self, out_arr, context=None):
        ret = super(YTArray, self).__array_wrap__(out_arr, context)
        if isinstance(ret, YTQuantity) and ret.shape != ():
            ret = ret.view(YTArray)
        if context is None:
            if ret.shape == ():
                return ret[()]
            return ret
        elif len(context[1]) == 1:
            # unary operators
            u = getattr(context[1][0], 'units', None)
            unit = self._ufunc_registry[context[0]](u)
            if unit is None:
                ret = np.array(ret)
            else:
                ret.units = unit
        elif len(context[1]) in (2,3):
            if len(context[1]) == 3:
                # note we use `is`, not ==.
                # They should be at the same location in memory
                if out_arr is not context[1][2]:
                    raise RuntimeError("Operation is not defined.")
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
                ret = np.array(ret)
            else:
                ret.units = unit
        else:
            raise RuntimeError("Operation is not defined.")
        return ret

    def __reduce__(self):
        """Pickle reduction method

        See the documentation for the standard library pickle module:
        http://docs.python.org/2/library/pickle.html

        Unit metadata is encoded in the zeroth element of third element of the 
        returned tuple, itself a tuple used to restore the state of the ndarray.  
        This is always defined for numpy arrays.
        """
        np_ret = super(YTArray, self).__reduce__()
        obj_state = np_ret[2]
        unit_state = (((str(self.units), self.units.registry.lut),) + obj_state[:],)
        new_ret = np_ret[:2] + unit_state + np_ret[3:]
        return new_ret

    def __setstate__(self, state):
        """Pickle setstate method

        This is called inside pickle.read() and restores the unit data from the
        metadata extracted in __reduce__ and then serialized by pickle.
        """
        super(YTArray, self).__setstate__(state[1:])
        unit, lut = state[0]
        registry = UnitRegistry(lut=lut, add_default_symbols=False)
        self.units = Unit(unit, registry=registry)

class YTQuantity(YTArray):
    def __new__(cls, input, input_units=None, registry=None, dtype=None):
        if not isinstance(input, (numeric_type, np.number)):
            raise RuntimeError('Quantity values must be numeric')
        ret = YTArray.__new__(cls, input, input_units, registry, dtype=dtype)
        if ret.size > 1:
            raise RuntimeError
        return ret

    @property
    def value(self):
        return np.array(self)

def uconcatenate(arrs, *args, **kwargs):
    v = np.concatenate(arrs, *args, **kwargs)
    if not any(isinstance(a, YTArray) for a in arrs):
        return v
    if not all(isinstance(a, YTArray) for a in arrs):
        raise RuntimeError("Not all of your arrays are YTArrays.")
    a1 = arrs[0]
    if not all(a.units == a1.units for a in arrs[1:]):
        raise RuntimeError("Your arrays must have identical units.")
    v.units = a1.units
    return v
