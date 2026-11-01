"""Parent node representing one physical Araknis switch."""

import udi_interface


class AraknisSwitch(udi_interface.Node):
    id = 'araknisswitch'

    drivers = [
        {
            'driver': 'ST',
            'value': 0,
            'uom': 25,
            'name': 'Connection Status',
        }
    ]

    def set_online(self, online):
        self.setDriver('ST', 1 if online else 0)

    def query(self, command=None):
        self.reportDrivers()

    commands = {'QUERY': query}
