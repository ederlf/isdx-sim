#!/usr/bin/python

import argparse
import log
import util
from config import Config
from pctrl import PCtrl

def create_pctrl(mid, config):
    logger = log.getLogger("P_" + str(mid))
    return PCtrl(mid, config, logger)

def main():

    parser = argparse.ArgumentParser(description="Simulates iSDX generation of flows according to BGP announcements and configured outbound policies")
    parser.add_argument("members", type=int, help="the number of IXP members")
    parser.add_argument("max_policies", type=int,
                        help="maximum number of outbound policies every participant will generate")
    parser.add_argument("routes", type=str, help="path to the announcements")
    parser.add_argument("--templates", type=str,
                        help="Path to the template files")
    
    args = parser.parse_args()
    config = Config(args.members, args.max_policies, args.routes, args.templates)

    # Create Participant Controllers from config.members
    pctrls = [create_pctrl(mid, config.members[mid]) for mid in config.members]
    updates =  config.route_set["updates"]

    for update in updates:
        for pctrl in pctrls:
            pctrl.process_event(update)

if __name__ == "__main__": 
    main()

