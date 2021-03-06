from numba import jit, float64

from ..parameter import Parameter
from ..processor import Processor
from ..parameter_list import ParameterList

@jit(nopython=True)
def n_process(data, invert):
    if invert:
        return -1.0 * data
    else:
        return  1.0 * data

class PolarityInverter(Processor):
    def __init__(self, name="Inverter", parameters=None, block_size=512, sample_rate=44100):

        super().__init__(name, parameters, block_size, sample_rate)

        if not parameters:
            self.parameters = ParameterList()
            self.parameters.add(Parameter("invert", False, "bool", processor=None, p=0.2))

    def process(self, data):
        return n_process(data, self.parameters.invert.value)

    def update(self, parameter_name):
        pass
