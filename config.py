# Major part is from Jeroen Schutrup's script to generate iSDX flows 
# https://github.com/jeroen92/iSDX/blob/master/scripts/routeToJson.py

import random
from netaddr import IPNetwork
import json 
import util
import copy 

class Config(object):
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
        self.gen_members_policies()

    # Receives a file with routes that will be announced by respective peers
    # The format of the file must be as follows:
    # ASN_NUMBER;IP/PREFIX;AS_PATH 
    # e.g.: 34872;93.123.28.0/23;[34872, 34224]
    # ASN Number: the Autonomous System Number of the peer.
    # IP/PREFIX: the prefix announced by the ASN. 
    # AS_PATH: the path to reach the prefix from the ASN. 
    # For now, no support for communities or MED. It should be easy to add. 
    def parse_routes(self):
        
        def create_update(ip, asn, prefix, as_path, community = None, med = None):
            update = copy.deepcopy(self.update_template)
            update["neighbor"]["ip"] = ip
            update["neighbor"]["address"]["peer"] = ip
            update["neighbor"]["asn"]["peer"] = asn
            update["neighbor"]["message"]["update"]["attribute"]["as-path"] = as_path
            if community: update["neighbor"]["message"]["update"]["attribute"]["community"] = community
            if med: update["neighbor"]["message"]["update"]["attribute"]["med"] = med
            update["neighbor"]["message"]["update"]["announce"]["ipv4 unicast"][ip] = {}
            update["neighbor"]["message"]["update"]["announce"]["ipv4 unicast"][ip][prefix] = {}
            bgp_msg = {"bgp": update}
            return bgp_msg

        f = open(self.ribdump, 'r')
        routes = f.readlines()
        ips = IPNetwork('172.0.0.0/16').iter_hosts()

        updates = []
        ases = {}
        route_set = {}
        
        for route in routes:
            asn, prefix, path = route.strip('\n').split(';')
            # TODO: consider adding multiple ports for an AS. Now it does not make much of a difference.
            if asn not in ases:
                ases[asn] = str(next(ips)) 
            ip = ases[asn]
            update = create_update(ip, asn, prefix, json.loads(path))
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
            member = {}
            member["Mode"] = self.sdx_template["Mode"]
            member["VMAC"] = self.sdx_template["VMAC"]
            member["VNHs"] = "10.0.0.1/8"
            member["Ports"] = ports
            member["ASN"] = asn
            member["Peers"] = peers
            member["Inbound Rules"] = inbound
            member["Outbound Rules"] = outbound
            member["Flanc Key"] = "Part%sKey" % mid
            return member


        # Everyone peers at the route server, so there is a full mesh of peers
        full_mesh = [i for i in range(1, len(self.route_set["ases"])+1)]
        mid = 1
        port_num = 4
        members = {}
        all_nhops = {}
        for asn in self.route_set["ases"]:
            member_ports = []
            ip = self.route_set["ases"][asn]
            member_ports.append({"Id": port_num, "MAC": util.randomMAC(), "IP": ip})
            members[str(mid)] = create_member(mid, asn, full_mesh, False, True, member_ports)
            port_num += 1
            all_nhops[ip] = mid
            mid += 1

        for m in members:
            members[m]["Next Hops"] = all_nhops

        return members

    def gen_members_policies(self):
        for mid, member in self.members.items():
            policies = {"outbound": list()}
            pid = 1
            while True:
                if len(self.route_set["ases"]) < 10:
                    rand_members = random.sample(range(1, len(self.route_set["ases"])), self.nmembers-1)
                    if any(x in member["Ports"] for x in rand_members):
                        continue
                    else:
                        break
                else:
                    rand_members = random.sample(range(1, len(self.route_set["ases"])), int(self.nmembers / 10))
                    if any(x in member["Ports"] for x in rand_members):
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

            self.members[mid]["Policies"] = policies
            # with open('policies/participant_%s.py' % (mid), 'w') as pfile:
            #     pfile.write(json.dumps(policies, indent=4))
            #     pfile.close()


def main():
    config = Config(9, 4, "routes.txt")

if __name__ == "__main__":
    main()
