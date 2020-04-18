# Major part is from Jeroen Schutrup's script to generate iSDX flows 
# https://github.com/jeroen92/iSDX/blob/master/scripts/routeToJson.py

import random
from netaddr import IPNetwork
import json 
import util
import copy 

class GenConfig(object):
    def __init__(self, nmembers, npolicies, ribdump, path_templates = None):
        self.nmembers = nmembers
        self.npolicies = npolicies
        self.ribdump = ribdump
        if path_templates:
            self.path_templates = path_templates
        else:
            self.path_templates = "templates/"
        self.update_template = util.load_json_file(self.path_templates + "update.json")
        self.sdx_template = util.load_json_file(self.path_templates + "sdx.json")
        self.member_template = util.load_json_file(self.path_templates + "member.json")
        self.route_set = self.parse_routes()
        self.members = self.gen_ixp_members()

    def generate(self):
        # gen_ixp_config(members)
        self.gen_members_policies()
        self.gen_policy_file()

    # Receives a file with routes that will be announced by respective peers
    # The format of the file must be as follows:
    # ASN_NUMBER;IP/PREFIX;AS_PATH 
    # e.g.: 34872;93.123.28.0/23;[34872, 34224]
    # ASN Number: the Autonomous System Number of the peer.
    # IP/PREFIX: the prefix announced by the ASN. 
    # AS_PATH: the path to reach the prefix from the ASN. 
    # For now, no support for communities or MED. It should be easy to add. 
    def parse_routes(self):
        f = open(self.ribdump, 'r')
        routes = f.readlines()
        ips = IPNetwork('172.0.0.0/16')

        updates = []
        ases = {}
        route_set = {}
        
        for route in routes:
            asn, prefix, path = route.strip('\n').split(';')
            if asn not in ases:
                ases[asn] = ips.next()
            ip = ases[asn]
            update = {"ip": ip, "asn": asn, "prefix": prefix, "as_path":json.loads(path) }
            updates.append(update)

        route_set["ases"] = ases
        route_set["updates"] = updates
        f.close()

        return route_set
    

    # Every ASN is a unique participant
    # Get routes belonging to each participant
    # Every next hop belonging to the same participant gets its own port number on the IXP
    def gen_ixp_members(self):
        
        def create_member(mid, asn, peers, inbound, outbound, ports):
            member = copy.deepcopy(self.member_template)
            member["ports"] = ports
            member["asn"] = asn
            member["peers"] = peers
            member["inbound"] = inbound
            member["outbound"] = outbound
            member["flanc"] = "Part%sKey" % mid
            return member

        # Everyone peers at the route server, so there is a full mesh of peers
        full_mesh = [i for i in range(1, len(self.route_set["ases"])+1)]
        mid = 1
        port_num = 4
        members = {}
        for asn in self.route_set["ases"]:
            nhops = []
            member_ports = []
            routes = [ i for i in self.route_set["updates"] if i["asn"] == asn ]
            for route in routes:
                if route["ip"] in nhops:
                    continue
                member_ports.append({"id": port_num, "MAC": util.randomMAC(), "IP": route["ip"]})
                nhops.append(route["ip"])
                port_num += 1
            members[str(mid)] = create_member(mid, route["asn"], full_mesh, False, True, member_ports)
            mid += 1
        return members

    def gen_members_policies(self):
        for mid, member in self.members.items():
            policies = {"outbound": list()}
            pid = 1
            while True:
                if len(self.route_set["ases"]) < 10:
                    rand_members = random.sample(range(1, len(self.route_set["ases"])), self.nmembers-1)
                    if any(x in member["ports"] for x in rand_members):
                        continue
                    else:
                        break
                else:
                    rand_members = random.sample(range(1, len(self.route_set["ases"])), self.nmembers / 10)
                    if any(x in member["ports"] for x in rand_members):
                        continue
                    else:
                        break

            for member_policy in rand_members:
                for npolicies in range(0, random.randint(1, self.npolicies)):
                    rand_port = random.randint(1, 65536)
                    policies["outbound"].append({
                        "cookie": pid,
                        "match": {
                            "tcp_dst": rand_port
                        },
                        "action": {
                            "fwd": member_policy
                        }
                    })
                    pid += 1

            with open('policies/participant_%s.py' % (mid), 'w') as pfile:
                pfile.write(json.dumps(policies, indent=4))
                pfile.close()

    def gen_policy_file(self):
        with open('config/sdx_policies.cfg', 'w') as pfile:
            pfile.write(json.dumps({ str(i): 'participant_%s.py' % str(i) for i in range(1, self.nmembers + 1) }))
            pfile.close()


    def create_update(self, ip, asn, prefix, as_path, community = None, med = None):
        update = copy.deepcopy(self.update_template)
        update["neighbor"]["ip"] = ip
        update["neighbor"]["address"]["peer"] = ip
        update["neighbor"]["asn"]["peer"] = asn
        update["neighbor"]["message"]["update"]["attribute"]["as-path"] = as_path
        if community: update["neighbor"]["message"]["update"]["attribute"]["community"] = community
        if med: update["neighbor"]["message"]["update"]["attribute"]["med"] = med
        update["neighbor"]["message"]["update"]["announce"]["ipv4 unicast"][ip] = {}
        update["neighbor"]["message"]["update"]["announce"]["ipv4 unicast"][ip][prefix] = {}
        return update

    def gen_ixp_config(self, members):
        self.sdx_template["Participants"] = self.members
        # I need to think how the topologies will look like
        # Right now there is just need for the SDX config
        # The topology configuration can be simplified for easier parsing too.

        # mainSwFabricConnections = dict()
        # for participantId, participant in participants.iteritems():
        #     ports = [ port["Id"] for port in participant["Ports"]]
        #     if len(ports) <= 1:
        #         ports = ports[0]
        #     mainSwFabricConnections[participantId] = ports
        # mainSwFabricConnections["arp"] = 1
        # mainSwFabricConnections["route server"] = 2
        # mainSwFabricConnections["refmon"] = 3
        # self.sdx_template["RefMon Settings"]["fabric connections"]["main"] = mainSwFabricConnections
        # self.sdx_template["VNHs"] = "10.0.0.1/8"
        # with open('%s/examples/test-mtsim/config/sdx_global.cfg' % args.path, 'w') as configFile:
        #     configFile.write(json.dumps(self.sdx_template, indent=4))
        #     configFile.close()


def main():
    g = GenConfig(9, 4, "routes.txt")
    g.generate()

if __name__ == "__main__":
    main()
