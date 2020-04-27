import json
import numpy as np

class Switch(object):
    """docstring for Switch"""
    def __init__(self, name, tables):
        self.name = name
        self.tables = {n:{} for n in tables}
        # self.arg = arg
        
    def add_flow(self, flow):
        match = json.dumps(flow["match"])
        table = flow["rule_type"]
        self.tables[table][match] = flow

    def del_flow(self, flow):
        del_match = flow["match"]
        table = flow["rule_type"]
        str_matches = list(self.tables[table].keys())
        for str_match in str_matches:
            flow_match = self.tables[table][str_match]["match"]
            delete = True
            for field in del_match:
                if field not in flow_match:
                    delete = False
                    break

                if del_match[field] != flow_match[field]:
                    delete = False
                    break
            
            if delete:
                del self.tables[table][str_match]

    def process_flow(self, flow):
        if flow["mod_type"] == 'remove':
            self.del_flow(flow)
        else:
            self.add_flow(flow)

    def dump_flows(self):
        for table in self.tables:
            for flow in self.tables[table]:
                print(flow)

    def total_table_flows(self, table):
        return len(self.tables[table])

class MultiHopTopo(object):
    def __init__(self, members, nedges, ncores):
        self.edges = {}
        self.cores = {}
        self.members = members

        for i in range(1, nedges+1):
            name = "edge%s" % i
            self.edges[name] = Switch(name, ["outbound"])

        for i in range(1, nedges+1):
            name = "edge%s" % i
            self.cores[name] = Switch(name, ["inbound"])

    def get_edge_distribution(self, nmembers, probs = []):
        # pick switches with normal distribution
        picks = []
        size = len(probs)

        edges = list(self.edges.keys())
        while True:
            if not size:
                dist = np.random.choice(edges, nmembers)

            # Guarantee that all switches will have members allocated 
            if set(edges) == set(dist):
                    return dist
  
        if len(self.edges) == size:
            dist = np.random.choice(edges, nmembers, p=probs)

        return None

    def handle_flows(self, flows):
        member = flows["auth_info"]["participant"]
        ports = self.members[member]["Ports"]
        flow_mods = flows["flow_mods"]
        for flow in flow_mods:
            # Install inbound in every core
            if flow["rule_type"] == "inbound":
                for sw in self.cores:
                    core = self.cores[sw]
                    core.process_flow(flow)
            # Install outbound on the respective switches
            elif flow["rule_type"] == "outbound":
                for port in ports:
                    sw_name = port["switch"]
                    edge = self.edges[sw_name]
                    edge.process_flow(flow)

    def num_flows_per_edge(self):
        return {sw:self.edges[sw].total_table_flows("outbound") for sw in self.edges}
        
    def num_flows_per_core(self):
        return {sw:self.cores[sw].total_table_flows("inbound") for sw in self.cores}
            
