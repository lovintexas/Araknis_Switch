"""Switch-wide PoE totals node."""
import udi_interface

Node = udi_interface.Node


class PoeSummary(Node):
    id = 'poesummary'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 73, 'name': 'Total PoE Power'},
        {'driver': 'POE_BUDGET', 'value': 0, 'uom': 73, 'name': 'PoE Budget'},
    ]

    def apply(self, data):
        self.setDriver('ST', data['total'])
        self.setDriver('POE_BUDGET', data['budget'])

    def query(self, command=None):
        self.reportDrivers()

    commands = {'QUERY': query}
