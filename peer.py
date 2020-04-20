#!/usr/bin/env python
#  Author:
#  Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#  Rudiger Birkner (Networked Systems Group ETH Zurich)
#  Arpit Gupta (Princeton)

import time
import os
import sys
import log

from decision_process import best_path_selection
from rib import rib, RibTuple


class BGPPeer(object):

    def __init__(self, id, asn, ports, peers_in, peers_out):
        self.id = id
        self.asn = asn
        self.ports = ports
        self.logger = log.getLogger('P'+str(self.id)+'-peer')

        self.rib = rib(self.asn)

        # peers that a participant accepts traffic from and sends advertisements to
        self.peers_in = peers_in
        # peers that the participant can send its traffic to and gets advertisements from
        self.peers_out = peers_out


    def update(self, route):
        updates = []
        key = {}

        origin = None
        as_path = None
        med = None
        atomic_aggregate = None
        community = None

        route_list = []
        # Extract out neighbor information in the given BGP update
    
        neighbor = route["neighbor"]["ip"]
        #self.logger.debug('==>>> '+str(neighbor)+' '+str(route))

        if ('state' in route['neighbor'] and route['neighbor']['state']=='down'):
            #TODO WHY NOT COMPLETELY DELETE LOCAL?
            self.logger.debug("neighbor " + str(neighbor))
            
            routes = self.rib.get_neighbor_prefixes_input(neighbor)
            
            self.logger.debug("routes: " + str(routes))

            for route_item in routes:
                self.logger.debug("route prefix in routes " + str(route_item.prefix))
                
                deleted_route = self.rib.get_input(route_item.prefix, neighbor)

                self.logger.debug("deleted_route : " + str(deleted_route))
                if deleted_route != None:

                    self.rib.delete_input(neighbor, route_item.prefix)
                    route_list.append({'withdraw': deleted_route})
                    self.logger.debug(str({'withdraw': deleted_route}))

            return route_list

        if ('update' in route['neighbor']['message']):
            if ('attribute' in route['neighbor']['message']['update']):
                attribute = route['neighbor']['message']['update']['attribute']

                origin = attribute['origin'] if 'origin' in attribute else ''

                as_path = attribute['as-path'] if 'as-path' in attribute else []
                #self.logger.debug("AS PATH SYNTAX:: "+str(as_path))

                med = attribute['med'] if 'med' in attribute else ''

                community = attribute['community'] if 'community' in attribute else ''
                communities = ''
                for c in community:
                    communities += ':'.join(map(str,c)) + " "

                atomic_aggregate = attribute['atomic-aggregate'] if 'atomic-aggregate' in attribute else ''

            if ('announce' in route['neighbor']['message']['update']):
                announce = route['neighbor']['message']['update']['announce']
                if ('ipv4 unicast' in announce):
                    for next_hop in announce['ipv4 unicast'].keys():
                        for prefix in announce['ipv4 unicast'][next_hop].keys():
                            #self.logger.debug("::::PREFIX::::: "+str(prefix)+" "+str(type(prefix)))
                            # TODO: Check if this appending the announced route to the input rib?
                            attributes = RibTuple(prefix, neighbor, next_hop, origin, as_path, communities, med, atomic_aggregate)
                            self.rib.update_input(attributes)

                            # TODO: Avoid multiple interactions with the DB
                            announce_route = self.rib.get_input(prefix, neighbor)

                            announce_route = self.rib.get_input(neighbor, prefix)
                            if announce_route is None:
                                self.logger.debug('-------------- announce_route is None')
                                self.rib['input'].dump(logger)
                                self.logger.debug('--------------')
                                self.logger.debug(str(prefix)+' '+str(neighbor))
                                assert(announce_route is not None)
                            else:
                                route_list.append({'announce': announce_route})

            elif ('withdraw' in route['neighbor']['message']['update']):
                withdraw = route['neighbor']['message']['update']['withdraw']
                if ('ipv4 unicast' in withdraw):
                    for prefix in withdraw['ipv4 unicast'].keys():
                        deleted_route = self.rib.get_input(neighbor, prefix)
                        if deleted_route != None:
                            self.rib.delete_input(neighbor, prefix)
                            route_list.append({'withdraw': deleted_route})

        return route_list


    def decision_process_local(self, update):
        'Update the local rib with new best path'
        if ('announce' in update):

            # TODO: Make sure this logic is sane.
            '''Goal here is to get all the routes in participant's input
            rib for this prefix. '''

            # NOTES:
            # Currently the logic is that we push the new update in input rib and then
            # make the best path decision. This is very efficient. This is how it should be
            # done:
            # (1) For announcement: We need to compare between the entry for that
            # prefix in the local rib and new announcement. There is not need to scan
            # the entire input rib. The compare the new path with output rib and make
            # deicision whether to announce a new path or not.
            # (2) For withdraw: Check if withdraw withdrawn route is same as
            # best path in local, if yes, then delete it and run the best path
            # selection over entire input rib, else just ignore this withdraw
            # message.

            announce_route = update['announce']
            #self.logger.debug("decision process local:: "+str(announce_route))
            prefix = announce_route.prefix
            self.logger.debug(" Peer Object for: "+str(self.id)+" --- processing update for prefix: "+str(prefix))
            current_best_route = self.rib.get_local(prefix)
            if current_best_route:
                # This is what should be fed to the desicion process
                routes = [announce_route, current_best_route]
                new_best_route = best_path_selection(routes)
            else:
                # This is the first time for this prefix
                new_best_route = announce_route

            self.logger.debug(" Peer Object for: "+str(self.id)+" ---Best Route after Selection: "+str(prefix)+' '+str(new_best_route))
            if bgp_routes_are_equal(new_best_route, current_best_route):
                self.logger.debug(" Peer Object for: "+str(self.id)+" --- No change in Best Path...move on "+str(prefix))
            else:
                #self.logger.debug('decision_process_local: announce: new_best_route: '+str(type(new_best_route))+' '+str(new_best_route))
                self.rib.update_local(new_best_route)
                # Check
                updated_best_path = self.rib.get_local(prefix)
                self.logger.debug(" Peer Object for: "+str(self.id)+" Pushed: "+str(new_best_route)+" Observing: "+str(updated_best_path))
                self.logger.debug(" Peer Object for: "+str(self.id)+" --- Best Path changed: "+str(prefix)+' '+str(new_best_route)+" Older best route: "+str(current_best_route))

        elif('withdraw' in update):
            deleted_route = update['withdraw']
            prefix = deleted_route.prefix
            self.logger.debug(" Peer Object for: "+str(self.id)+" ---processing withdraw for prefix: "+str(prefix))
            if deleted_route is not None:
                # delete route if being used
                current_best_route = self.rib.get_local(prefix)
                if current_best_route:
                    # Check if current_best_route and deleted_route are advertised by the same guy

                    if deleted_route.neighbor == current_best_route.neighbor:
                        # TODO: Make sure this logic is sane.
                        '''Goal here is to get all the routes in participant's input
                        rib for this prefix. '''
                        self.rib.delete_local(prefix)
                        routes = self.rib.get_all_prefix_input(prefix)
                        if routes:
                            #self.logger.debug('decision_process_local: withdraw: best_route: '+str(type(best_route))+' '+str(best_route))
                            best_route = best_path_selection(routes)
                            self.rib.update_local(best_route)
                        else:
                            self.logger.debug(" Peer Object for: "+str(self.id)+" ---No best route available for prefix "+str(prefix)+" after receiving withdraw message.")
                    else:
                        self.logger.debug(" Peer Object for: "+str(self.id)+" ---BGP withdraw for prefix "+str(prefix)+" has no impact on best path")
                else:
                    self.logger.debug(" Peer Object for: "+str(self.id)+" --- This is weird. How can we not have any delete object in this function")


    def bgp_update_peers(self, updates, prefix_2_VNH, ports):
        # TODO: Verify if the new logic makes sense
        changed_vnhs = []
        announcements = []
        for update in updates:
            if 'announce' in update:
                prefix = update['announce'].prefix
            else:
                prefix = update['withdraw'].prefix

            prev_route = self.rib.get_output(prefix)
            #prev_route["next_hop"] = str(prefix_2_VNH[prefix])

            best_route = self.rib.get_local(prefix)
            if best_route == None:
                # XXX: TODO: improve on this? give a chance for change to show up in db.
                time.sleep(.1)
                best_route = self.rib.get_local(prefix)
            self.logger.debug(" Peer Object for: "+str(self.id)+" -- Previous Outbound route: "+str(prev_route)+" New Best Path: "+str(best_route))
            if best_route == None:
                self.logger.debug('=============== best_route is None ====================')
                self.logger.debug(str(prefix))
                self.logger.debug('----')
                self.rib['local'].dump(self.logger)
                self.logger.debug('----')
                self.logger.debug(str(updates))
                self.logger.debug('----')
                self.logger.debug(str(update))
                self.logger.debug('----')
                self.logger.debug(str(self.rib.get_local(prefix)))
                self.logger.debug('----')
                assert(best_route is None)
            #self.logger.debug("**********best route for: "+str(prefix)+" route:: "+str(best_route))

            if ('announce' in update):
                # Check if best path has changed for this prefix
                if not bgp_routes_are_equal(best_route, prev_route):
                    # store announcement in output rib
                    # self.logger.debug(str(best_route)+' '+str(prev_route))
                    self.rib.update_output(best_route)

                    # add the VNH to the list of changed VNHs
                    changed_vnhs.append(prefix_2_VNH[prefix])
                    if best_route:
                        # announce the route to each router of the participant
                        for port in ports:
                            # TODO: Create a sender queue and import the announce_route function
                            #self.logger.debug ("********** Failure: "+str(port["IP"])+' '+str(prefix)+" route::failure "+str(best_route))
                            announcements.append(announce_route(port["IP"], prefix,
                                prefix_2_VNH[prefix], best_route.as_path))
                    else:
                        self.logger.debug("Race condition problem for prefix: "+str(prefix))
                        continue

            elif ('withdraw' in update):
                # A new announcement is only needed if the best path has changed
                if best_route:
                    "There is a best path available for this prefix"
                    if not bgp_routes_are_equal(best_route, prev_route):
                        "There is a new best path available now"
                        # store announcement in output rib
                        self.rib.update_output(best_route)

                        # add the VNH to the list of changed VNHs
                        self.logger.debug(" Peer Object for: "+str(self.id)+" ^^^bgp_update_peers:: "+str(best_route))
                        changed_vnhs.append(prefix_2_VNH[prefix])

                        for port in ports:
                            announcements.append(announce_route(port["IP"],
                                                 prefix, prefix_2_VNH[prefix],
                                                 best_route.as_path))

                else:
                    "Currently there is no best route to this prefix"
                    if prev_route:
                        # Clear this entry from the output rib
                        if prefix in prefix_2_VNH:
                            self.rib.delete_output(prefix)
                            for port in self.ports:
                                # TODO: Create a sender queue and import the announce_route function
                                announcements.append(withdraw_route(port["IP"],
                                    prefix,
                                    prefix_2_VNH[prefix]))

        return changed_vnhs, announcements


def bgp_routes_are_equal(route1, route2):
    if route1 is None:
        return False
    if route2 is None:
        return False
    if (route1.next_hop != route2.next_hop):
        return False
    if (route1.as_path != route2.as_path):
        return False
    return True


def announce_route(neighbor, prefix, next_hop, as_path):

    msg = "neighbor " + neighbor + " announce route " + prefix + " next-hop " + str(next_hop)
    msg += " as-path [ ( " + ' '.join(str(ap) for ap in as_path) + " ) ]"

    return msg


def withdraw_route(neighbor, prefix, next_hop):

    msg = "neighbor " + neighbor + " withdraw route " + prefix + " next-hop " + str(next_hop)

    return msg


''' main '''
if __name__ == '__main__':

    mypeer = BGPPeer(1, 10, [], [], [])
    import json


    route = json.loads('''{ "type": "update", "neighbor": { "ip": "172.0.0.21", "address": { "local": "172.0.255.254", "peer": "172.0.0.21"}, "asn": { "local": "65000", "peer": "300"}, "message": { "update": { "attribute": { "origin": "igp", "as-path": [ 300 ], "confederation-path": [], "med": 0 }, "announce": { "ipv4 unicast": {} } } }} }''')

    mypeer.update(route)

    print (mypeer.rib.loc_table)
