#!/usr/bin/python

import argparse
import log
import util
from config import Config
from pctrl import PCtrl
from topology import MultiHopTopo

def create_pctrl(mid, config):
    logger = log.getLogger("P_" + str(mid))
    return PCtrl(mid, config, logger)

def dict_str(d):
    return ','.join("{}:{}".format(k, v) for k, v in d.items())

def flows_per_member(topo, pctrl, updates):
    for update in updates:
        flows = pctrl.process_event(update)
        topo.handle_flows(flows)
    return sum(topo.num_flows_per_edge().values())

def main():

    parser = argparse.ArgumentParser(description="Simulates iSDX generation of flows according to BGP announcements and configured outbound policies")
    parser.add_argument("members", type=int, help="the number of IXP members")
    parser.add_argument("max_edges", type=int,
                        help="maximum number of edge switches")
    parser.add_argument("max_policies", type=int,
                        help="maximum number of outbound policies every participant will generate")
    parser.add_argument("routes", type=str, help="path to the announcements")
    parser.add_argument("--templates", type=str,
                        help="Path to the template files")
    
    args = parser.parse_args()
    config = Config(args.members, args.max_policies, args.routes, False)

    # TODO: Add number of edges and cores as running parameters.
    topo = MultiHopTopo(config.members, args.max_edges, 4)

    # Distribute participants among switches
    nports = sum([len(config.members[m]["Ports"]) for m in config.members])
    edge_dist = topo.get_edge_distribution(nports)

    memxedges = {}
    for i, m in enumerate(config.members):
        for port in config.members[m]["Ports"]:
            port["switch"] = edge_dist[i]
            if edge_dist[i] not in memxedges:
                memxedges[edge_dist[i]] = 0
            memxedges[edge_dist[i]] += 1

    # Create Participant Controllers from config.members
    pctrls = [create_pctrl(mid, config.members[mid]) for mid in list(config.members.keys())[0:config.member_cap]]
    updates =  config.route_set["updates"]
    flow_cnt = {x:0 for x in config.members}
    f = open("res-per-member/%s-%s" % (args.members, args.max_policies), 'w')
    for pctrl in pctrls:
        flow_cnt[pctrl.id] += flows_per_member(topo, pctrl, updates)
        f.write("%s;%s\n" % (pctrl.id, flow_cnt[pctrl.id]))
        topo.reset_switches()
    f.close()
    #for mid in flow_cnt:
    #    print("%s;%s" % (mid, flow_cnt[mid]))
    #for update in updates:
    #    for pctrl in pctrls:
    #        flows = pctrl.process_event(update)
    #        topo.handle_flows(flows)
    #print("%s;%s;%s" % (args.members, dict_str(memxedges), dict_str(topo.num_flows_per_edge() )))
    #print(sum(topo.num_flows_per_edge().values()))

if __name__ == "__main__": 
    main()

