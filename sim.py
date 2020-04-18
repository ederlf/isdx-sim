#!/usr/bin/python

import argparse
from config import Config

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

if __name__ == "__main__": 
    main()

