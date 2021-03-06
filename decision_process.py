#!/usr/bin/env python
#  Author:
#  Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#  Sean Donovan

import socket, struct

''' BGP decision process '''
def best_path_selection(routes):

    # Priority of rules to make decision:
    # ---- 0. [Vendor Specific - Cisco has a "Weight"]
    # ---- 1. Highest Local Preference
    # 2. Lowest AS Path Length
    # ---- 3. Lowest Origin type - Internal preferred over external
    # 4. Lowest  MED
    # ---- 5. eBGP learned over iBGP learned - so if the above's equal, and you're at a border router, send it out to the next AS rather than transiting
    # ---- 6. Lowest IGP cost to border routes
    # 7. Lowest Router ID (tie breaker!)
    #
    # I believe that steps 0, 1, 3, 5, and 6 are out

    ''' 1. Lowest AS Path Length '''

    best_routes = []

    for route in routes:
        #print route

        #find ones with smallest AS Path Length
        if not best_routes:
            #prime the pump
            min_route_length = aspath_length(route.as_path)
            best_routes.append(route)
        elif min_route_length == aspath_length(route.as_path):
            best_routes.append(route)
        elif min_route_length > aspath_length(route.as_path):
            best_routes = []
            min_route_length = aspath_length(route.as_path)
            best_routes.append(route)

    # If there's only 1, it's the best route

    if len(best_routes) == 1:
        #print "Shortest A"
        return best_routes.pop()

    ''' 2. Lowest MED '''

    # Compare the MED only among routes that have been advertised by the same AS.
    # Put it differently, you should skip this step if two routes are advertised by two different ASes.

    # get the list of origin ASes
    as_list = []
    post_med_best_routes = []
    for route in best_routes:
        as_list.append(get_advertised_as(route.as_path))

    # sort the advertiser's list and
    # look at ones who's count != 1
    as_list.sort()

    i = 0
    while i < len(as_list):

        if as_list.count(as_list[i]) > 1:

            # get all that match the particular AS
            from_as_list = [x for x in best_routes if get_advertised_as(x.as_path)==as_list[i]]

            # MED comparison here
            j = 0
            lowest_med = from_as_list[j].med

            j += 1
            while j < len(from_as_list):
                if lowest_med > from_as_list[j].med:
                    lowest_med = from_as_list[j].med
                j += 1

            # add to post-MED list - this could be more than one if MEDs match
            temp_routes = [x for x in from_as_list if x.med==lowest_med]
            for el in temp_routes:
                post_med_best_routes.append(el)

            i = i+as_list.count(as_list[i])

        else:
            temp_routes = [x for x in best_routes if get_advertised_as(x.as_path)==as_list[i]]
            for el in temp_routes:
                post_med_best_routes.append(el)
            i += 1

    # If there's only 1, it's the best route
    if len(post_med_best_routes) == 1:
        #print "M"
        return post_med_best_routes.pop()

    ''' 3. Lowest Router ID '''

    # Lowest Router ID - Origin IP of the routers left.
    i = 0
    lowest_ip_as_long = ip_to_long(post_med_best_routes[i].next_hop)

    i += 1
    while i < len(post_med_best_routes):
        if lowest_ip_as_long > ip_to_long(post_med_best_routes[i].next_hop):
            lowest_ip_as_long = ip_to_long(post_med_best_routes[i].next_hop)
        i += 1

    #print "R"
    return post_med_best_routes[get_index(post_med_best_routes,'next_hop',long_to_ip(lowest_ip_as_long))]


''' Helper functions '''
def aspath_length(as_path):
    return len(as_path)

def get_advertised_as(as_path):
    return as_path[0]

def ip_to_long(ip):
    return struct.unpack('!L', socket.inet_aton(ip))[0]

def long_to_ip(ip):
    return socket.inet_ntoa(struct.pack('!L', ip))

def get_index(seq, attr, value):
    return next(index for (index, d) in enumerate(seq) if getattr(d, attr) == value)
