#  Author:
#  Arpit Gupta (Princeton)
#  Robert MacDavid (Princeton)


import argparse
import atexit
import json
import os
from sys import exit
import time

import sys
import log
import util

from netaddr import IPNetwork

from flowmodmsg import FlowModMsgBuilder
from peer import BGPPeer
from ss_lib import vmac_part_port_match
from ss_rule_scheme import update_outbound_rules, init_inbound_rules, init_outbound_rules, msg_clear_all_outbound
from supersets import SuperSets
from rib import ARPEntry

TIMING = True

class PConfig(object):

    MULTISWITCH = 0
    MULTITABLE  = 1
    MULTIHOP = 2

    SUPERSETS = 0
    MDS       = 1

    def __init__(self, config, id):
        self.id = str(id)
        self.config = config
        self.parse_modes()
        self.parse_various()

    def parse_modes(self):
        config = self.config

        mode = config["Mode"]
        if  mode == "Multi-Switch":
            self.dp_mode = self.MULTISWITCH
        elif mode == "Multi-Hop":
            self.dp_mode = self.MULTIHOP
        else:
            self.dp_mode = self.MULTITABLE

        vmac_cfg = config["VMAC"]

        if vmac_cfg["Mode"] == "Superset":
            self.vmac_mode = self.SUPERSETS
        else:
            self.vmac_mode = self.MDS

        self.vmac_options = vmac_cfg["Options"]


    def parse_various(self):
        config = self.config

        self.ports = config["Ports"]
        self.port0_mac = self.ports[0]["MAC"]

        self.peers_in = config["Peers"]
        self.peers_out = self.peers_in

        self.asn = config["ASN"]

        self.VNHs = IPNetwork(config["VNHs"])

    def get_macs(self):
        return [port['MAC'] for port in self.ports]

    def get_ports(self):
        return [port['IP'] for port in self.ports]

    def get_bgp_instance(self):
        return BGPPeer(self.id, self.asn, self.ports, self.peers_in, self.peers_out)

    def isMultiSwitchMode(self):
        return self.dp_mode == self.MULTISWITCH

    def isMultiTableMode(self):
        return self.dp_mode == self.MULTITABLE

    def isMultiHopMode(self):
        return self.dp_mode == self.MULTIHOP

    def isSupersetsMode(self):
        return self.vmac_mode == self.SUPERSETS

    def isMDSMode(self):
        return self.vmac_mode == self.MDS


class PCtrl(object):
    def __init__(self, id, config, logger):
        # participant id
        self.id = id
        # print ID for logging
        self.logger = logger

        # used to signal termination
        self.run = True
        self.prefix_lock = {}
        self.arp_table = {}


        # Initialize participant params
        self.cfg = PConfig(config, self.id)
        # Vmac encoding mode
        # self.cfg.vmac_mode = config_file["vmac_mode"]
        # Dataplane mode---multi table or multi switch
        # self.cfg.dp_mode = config_file["dp_mode"]


        self.policies = self.cfg.config["Policies"]

        # The port 0 MAC is used for tagging outbound rules as belonging to us
        self.port0_mac = self.cfg.port0_mac

        self.nexthop_2_part = self.cfg.config["Next Hops"]

        # VNHs related params
        self.num_VNHs_in_use = 0
        self.VNH_2_prefix = {}
        self.prefix_2_VNH = {}

        # Keeps track of the current participant that is the default next hop for VNHs
        self.nhpart_2_VNHs = {}

        # Superset related params
        if self.cfg.isSupersetsMode():
            self.supersets = SuperSets(self, self.cfg.vmac_options)
        else:
            # TODO: create similar class and variables for MDS
            self.mds = None

        # Keep track of flow rules pushed
        self.dp_pushed = []
        # Keep track of flow rules which are scheduled to be pushed
        self.dp_queued = []

        self.bgp_instance = BGPPeer(id, self.cfg.asn, self.cfg.ports, self.cfg.peers_in, self.cfg.peers_out)

        self.fm_builder = FlowModMsgBuilder(self.id)

    def sanitize_policies(self, policies):

        port_count = len(self.cfg.ports)

        # sanitize the input policies
        if 'inbound' in policies:
            for policy in policies['inbound']:
                if 'action' not in policy:
                    continue
                if 'fwd' in policy['action'] and int(policy['action']['fwd']) >= port_count:
                    policy['action']['fwd'] = 0

        return policies


    def load_policies(self, policy_file):
        # Load policies from file

        with open(policy_file, 'r') as f:
            policies = json.load(f)

        return self.sanitize_policies(policies)


    def initialize_dataplane(self):
        "Read the config file and update the queued policy variable"

        self.logger.info("Initializing inbound rules")

        final_switch = "main-in"
        if self.cfg.isMultiTableMode() or self.cfg.isMultiHopMode():
            final_switch = "main-out"

        self.init_vnh_assignment()

        rule_msgs = init_inbound_rules(self.id, self.policies,
                                        self.supersets, final_switch)
        self.logger.debug("Rule Messages INBOUND:: "+str(rule_msgs))

        rule_msgs2 = init_outbound_rules(self, self.id, self.policies,
                                        self.supersets, final_switch)
        self.logger.debug("Rule Messages OUTBOUND:: "+str(rule_msgs2))

        if 'changes' in rule_msgs2:
            if 'changes' not in rule_msgs:
                rule_msgs['changes'] = []
            rule_msgs['changes'] += rule_msgs2['changes']

        #TODO: Initialize Outbound Policies from RIB
        self.logger.debug("Rule Messages:: "+str(rule_msgs))
        if 'changes' in rule_msgs:
            self.dp_queued.extend(rule_msgs["changes"])


    def push_dp(self):
        '''
        (1) Check if there are any policies queued to be pushed
        (2) Send the queued policies to reference monitor
        '''

        # it is crucial that dp_queued is traversed chronologically
        for flowmod in self.dp_queued:
            self.fm_builder.add_flow_mod(**flowmod)
            self.dp_pushed.append(flowmod)

        # reset queue
        self.dp_queued = []

        flows = self.fm_builder.get_msg()
        
        self.fm_builder.reset_flow_mod()

        return flows
        
        # reset flow_mods after send - self.flow_mods = []
        


    def process_event(self, data, mod_type=None):  
        "Locally process each incoming network event"

        if 'bgp' in data:
            self.logger.debug("Event Received: BGP Update.")
            route = data['bgp']
            # Process the incoming BGP updates from XRS
            #self.logger.debug("BGP Route received: "+str(route)+" "+str(type(route)))
            return self.process_bgp_route(route)

        elif 'policy' in data:
            # Process the event requesting change of participants' policies
            self.logger.debug("Event Received: Policy change.")
            change_info = data['policy']
            for element in change_info:
                if 'remove' in element:
                    self.process_policy_changes(element['remove'], 'remove')
                    #self.logger.debug("PART_Test: REMOVE: %s" % element)
                if 'insert' in element:
                    self.process_policy_changes(element['insert'], 'insert')
                    #self.logger.debug("PART_Test: INSERT: %s" % element)

        elif 'arp' in data:
            if data['arp'] == 1:
                ip = data['SPA']
                mac = data['SHA']
                part = data['participant'] 
                if part not in self.nhpart_2_VNHs:
                    self.nhpart_2_VNHs[part] = []

                if ip not in self.nhpart_2_VNHs[part]:
                    self.nhpart_2_VNHs[part].append(ip)
                newbest = (part, mac)
                if ip not in self.arp_table:
                    self.arp_table[ip] = ARPEntry(newbest, None) 
                else:
                    ae = self.arp_table[ip]
                    # Modify only if it is an actual change
                    if self.arp_table[ip].best_hop != newbest:
                        self.arp_table[ip] = ARPEntry(newbest, ae.best_hop)
            else:
                (requester_srcmac, requested_vnh) = tuple(data['arp'])
                self.logger.debug("Event Received: ARP request for IP "+str(requested_vnh))
                self.process_arp_request(requester_srcmac, requested_vnh)

        else:
            self.logger.warn("UNKNOWN EVENT TYPE RECEIVED: "+str(data))
    
    def process_message(self, msg):
        mtype = msg["msg_type"]
        if mtype == "linkdown":    
            part = msg["participant"]
            if part not in self.nhpart_2_VNHs:
                return
            vnhs = self.nhpart_2_VNHs[part]        
            for v in vnhs:
                best = self.arp_table[v].best_hop
                second = self.arp_table[v].prev_hop
                if part == best[0] and second:
                    # Send ARP with available second best-hop
                    for port in self.cfg.ports:
                        self.process_arp_request(port["MAC"], v, second[1])


    def process_policy_changes(self, change_info, mod_type):
        # idea to remove flow rules for the old policies with cookies
        '''
        removal_msgs = []
        for element in change_info:

            if 'removal_cookies' in element:
        
                for cookie in element['removal_cookies']:
                    cookie_id = (cookie['cookie'],65535)
                    match_args = cookie['match']
                    mod =  {"rule_type":"inbound", "priority":4,"match":{} , "action":{}, "cookie":cookie_id, "mod_type":"remove"}
                    removal_msgs.append(mod)
        
        self.dp_queued.extend(removal_msgs)
        '''

        # json file format for change_info - mod_type = remove or insert
        '''
        {
            "policy": [
            {
                mod_type: [ 
        
        # change_info begin

                    {
                        "inbound": [
                            { cookie1 ... match ... action }
                            { cookie2 ... match ... action }
                        ]
                    }

                    {
                        "outbound": [
                            { cookie1 ... match ... action }
                            { cookie2 ... match ... action }
                        ]
                    }

        # change_info end
                
                ]           // end mod_type-array
            }, 
            
            {
                mod_type: ...

            }

            ]               // end policy-array
        }
        '''

        policies = self.sanitize_policies(change_info)

        final_switch = "main-in"
        if self.cfg.isMultiTableMode():
            final_switch = "main-out"

        #self.init_vnh_assignment() // not used
        inbound_policies = {}
        outbound_policies = {}
        
        for element in policies:
            if 'inbound' in element:
                inbound_policies = element
            if 'outbound' in element:
                outbound_policies = element

        #self.logger.debug("PART_Test: INBOUND: %s" % inbound_policies)
        #self.logger.debug("PART_Test: OUTBOUND: %s" % outbound_policies)

        rule_msgs = init_inbound_rules(self.id, inbound_policies,
                                        self.supersets, final_switch)

        rule_msgs2 = init_outbound_rules(self, self.id, outbound_policies,
                                        self.supersets, final_switch)

        if 'changes' in rule_msgs2:
            if 'changes' not in rule_msgs:
                rule_msgs['changes'] = []
            rule_msgs['changes'] += rule_msgs2['changes']


        for rule in rule_msgs['changes']:
            rule['mod_type'] = mod_type


        #self.logger.debug("PART_Test: Rule Msgs: %s" % rule_msgs)

        if 'changes' in rule_msgs:
            self.dp_queued.extend(rule_msgs["changes"])

        self.push_dp()


    def process_bgp_route(self, route):
        "Process each incoming BGP advertisement"
        tstart = time.time()

        # Map to update for each prefix in the route advertisement.
        updates = self.bgp_instance.update(route)
        #self.logger.debug("process_bgp_route:: "+str(updates))
        # TODO: This step should be parallelized
        # TODO: The decision process for these prefixes is going to be same, we
        # should think about getting rid of such redundant computations.
        for update in updates:
            self.bgp_instance.decision_process_local(update)
            self.vnh_assignment(update)

        if TIMING:
            elapsed = time.time() - tstart
            self.logger.debug("Time taken for decision process: "+str(elapsed))
            tstart = time.time()

        if self.cfg.isSupersetsMode():
            ################## SUPERSET RESPONSE TO BGP ##################
            # update supersets
            "Map the set of BGP updates to a list of superset expansions."
            ss_changes, ss_changed_prefs = self.supersets.update_supersets(self, updates)

            if TIMING:
                elapsed = time.time() - tstart
                self.logger.debug("Time taken to update supersets: "+str(elapsed))
                tstart = time.time()

            # ss_changed_prefs are prefixes for which the VMAC bits have changed
            # these prefixes must have gratuitous arps sent
            garp_required_vnhs = [self.prefix_2_VNH[prefix] for prefix in ss_changed_prefs]

            "If a recomputation event was needed, wipe out the flow rules."
            if ss_changes["type"] == "new":
                self.logger.debug("Wiping outbound rules.")
                wipe_msgs = msg_clear_all_outbound(self.policies, self.port0_mac)
                self.dp_queued.extend(wipe_msgs)

                #if a recomputation was needed, all VMACs must be reARPed
                # TODO: confirm reARPed is a word
                garp_required_vnhs = self.VNH_2_prefix.keys()

            if len(ss_changes['changes']) > 0:

                self.logger.debug("Supersets have changed: "+str(ss_changes))

                "Map the superset changes to a list of new flow rules."
                flow_msgs = update_outbound_rules(ss_changes, self.policies,
                        self.supersets, self.port0_mac)

                self.logger.debug("Flow msgs: "+str(flow_msgs))
                "Dump the new rules into the dataplane queue."
                self.dp_queued.extend(flow_msgs)

            if TIMING:
                elapsed = time.time() - tstart
                self.logger.debug("Time taken to deal with ss_changes: "+str(elapsed))
                tstart = time.time()

        ################## END SUPERSET RESPONSE ##################

        else:
            # TODO: similar logic for MDS
            self.logger.debug("Creating ctrlr messages for MDS scheme")


        if TIMING:
            elapsed = time.time() - tstart
            self.logger.debug("Time taken to push dp msgs: "+str(elapsed))
            tstart = time.time()

        changed_vnhs, announcements = self.bgp_instance.bgp_update_peers(updates, self.prefix_2_VNH, self.cfg.ports)

        """ Combine the VNHs which have changed BGP default routes with the
            VNHs which have changed supersets.
        """

        changed_vnhs = set(changed_vnhs)
        changed_vnhs.update(garp_required_vnhs)

        # Send gratuitous ARP responses for all them
        # for vnh in changed_vnhs:
        #     self.process_arp_request(None, vnh)

        # Tell Route Server that it needs to announce these routes
        # for announcement in announcements:
        #     # TODO: Complete the logic for this function
        #     self.send_announcement(announcement)

        if TIMING:
            elapsed = time.time() - tstart
            self.logger.debug("Time taken to send garps/announcements: "+str(elapsed))
            tstart = time.time()

        return self.push_dp()

    def vnh_assignment(self, update):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            # TODO: Do we really need to assign a VNH for each advertised prefix?
            if ('announce' in update):
                prefix = update['announce'].prefix

                if (prefix not in self.prefix_2_VNH):
                    # get next VNH and assign it the prefix
                    self.num_VNHs_in_use += 1
                    vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])

                    self.prefix_2_VNH[prefix] = vnh
                    self.VNH_2_prefix[vnh] = prefix
        else:
            "Disjoint"
            # TODO: @Robert: Place your logic here for VNH assignment for MDS scheme
            self.logger.debug("VNH assignment called for disjoint vmac_mode")


    def init_vnh_assignment(self):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            # TODO: Do we really need to assign a VNH for each advertised prefix?
            #self.bgp_instance.rib["local"].dump()
            prefixes = self.bgp_instance.rib.get_local_prefixes()
            #print 'init_vnh_assignment: prefixes:', prefixes
            #print 'init_vnh_assignment: prefix_2_VNH:', self.prefix_2_VNH
            for prefix in prefixes:
                if (prefix not in self.prefix_2_VNH):
                    # get next VNH and assign it the prefix
                    self.num_VNHs_in_use += 1
                    vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])

                    self.prefix_2_VNH[prefix] = vnh
                    self.VNH_2_prefix[vnh] = prefix
        else:
            "Disjoint"
            # TODO: @Robert: Place your logic here for VNH assignment for MDS scheme
            self.logger.debug("VNH assignment called for disjoint vmac_mode")


def get_prefixes_from_announcements(route):
    prefixes = []
    if ('update' in route['neighbor']['message']):
        if ('announce' in route['neighbor']['message']['update']):
            announce = route['neighbor']['message']['update']['announce']
            if ('ipv4 unicast' in announce):
                for next_hop in announce['ipv4 unicast'].keys():
                    for prefix in announce['ipv4 unicast'][next_hop].keys():
                        prefixes.append(prefix)

        elif ('withdraw' in route['neighbor']['message']['update']):
            withdraw = route['neighbor']['message']['update']['withdraw']
            if ('ipv4 unicast' in withdraw):
                for prefix in withdraw['ipv4 unicast'].keys():
                    prefixes.append(prefix)
    return prefixes


def main():
    pass

if __name__ == '__main__':
    main()
