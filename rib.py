#!usr/bin/env python
#   Based on the previous implementation by:
#   Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#   Arpit Gupta (arpitg@cs.princeton.edu)
#   Author:
#   Eder Leao Fernandes (ederlf@tutanota.com)

from collections import namedtuple

# have all the rib implementations return a consistent interface
labels = ('prefix', 'neighbor', 'next_hop', 'origin', 'as_path', 'communities', 'med', 'atomic_aggregate')
RibTuple = namedtuple('RibTuple', labels)
arplabels = ('best_hop', 'prev_hop')
ARPEntry = namedtuple('ARPEntry', arplabels) 

def add_by_prefix(table, item):
    table[item.prefix] = item

class rib(object):

    def __init__(self, name):
        self.name = name 
        # The key is the neighbor IP
        # Each entry is a dictionary of prefixes sent/received to/by a neighbor
        self.in_table = {}
        # Local and Output are indexed by prefix only
        self.loc_table = {}
        self.out_table = {}

    def __del__(self):
        pass


    def update_local(self, item):
        assert(isinstance(item, RibTuple))
        add_by_prefix(self.loc_table, item)

    def update_output(self, item):
        assert(isinstance(item, RibTuple))
        add_by_prefix(self.out_table, item)        


    def update_input(self, item):
        assert(isinstance(item, RibTuple))
        if item.neighbor not in self.in_table:
            self.in_table[item.neighbor] = {}    
        
        self.in_table[item.neighbor][item.prefix] = item


    def get_local(self, prefix):
        if prefix in self.loc_table:
            return self.loc_table[prefix]
        return None

    def get_output(self, prefix):
        if prefix in self.out_table:
            return self.out_table[prefix]
        return None

    def get_input(self, neighbor, prefix):
        if neighbor in self.in_table:
            if prefix in self.in_table[neighbor]:
                return self.in_table[neighbor][prefix]
        return None

    def get_all_prefix_input(self, prefix):
        return [self.in_table[x][prefix] for x in self.in_table if prefix in self.in_table[x]]

    def get_neighbor_prefixes_input(self, neighbor):
        if neighbor in self.in_table:
            return self.in_table[neighbor]
        return None

    def get_local_prefixes(self):
        return sorted(self.loc_table.keys())
    
    def get_output_prefixes(self):
        return sorted(self.out_table.keys())    

    def delete_local(self, prefix):
        if prefix in self.loc_table:
            del self.loc_table[prefix]


    def delete_output(self, prefix):
        if prefix in self.out_table:
            del self.out_table[prefix]

    def delete_input(self, neighbor, prefix):
        if neighbor in self.in_table:
            if prefix in self.in_table[neighbor]:
                del self.in_table[neighbor][prefix]

    def delete_input_prefixes(self, prefix):
        for neigh in self.in_table:
            if prefix in self.in_table[neigh]:
                del self.in_table[neigh][prefix]


''' main '''
if __name__ == '__main__':

    myrib = rib('as1')
    myrib.update_input(RibTuple('171.0.0.0/24', '171.0.0.1', '171.0.0.2', 'igp', '100, 200, 300', '0', 0, 'false'))

    myrib.update_input(RibTuple('172.0.0.0/24', '172.0.0.1', '172.0.0.2', 'igp', '100, 200, 300', '0', 0, 'false'))

    print (myrib.get_all_prefix_input("171.0.0.0/24"))
    print (myrib.get_all_prefix_input("172.0.0.0/24"))
    
    myrib.update_input(RibTuple('172.0.0.0/24', '172.0.0.1', '173.0.0.2', 'igp', '100, 200, 300', '0', 0, 'false'))
    
    myrib.delete_input_prefixes(prefix='172.0.0.0/24')
    print (myrib.in_table)
    
