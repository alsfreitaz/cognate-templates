#!/usr/bin/env python

import yaml, itertools, os, argparse, random, shutil, glob

CONFIG_FILE = "config.yml"
COGNATE_INVENTORY_PATH = "inventory"
COGNATE_PROVISIONING_PATH = "provisioning"
COGNATE_INVENTORY_FILE = "cognate_inventory.yml"
COGNATE_TEMPLATE_SCRIPTS_FOLDER = "__scripts__"

def yaml_to_dict(filename):
    with open(filename) as file:
        config = yaml.load(file, Loader=yaml.FullLoader)
        return config

def ip_range(input_string):
    octets = input_string.split('.')
    chunks = [list(map(int, octet.split('-'))) for octet in octets]
    ranges = [range(c[0], c[1] + 1) if len(c) == 2 else c for c in chunks]
    for address in itertools.product(*ranges):
        yield '.'.join(list(map(str, address)))

def filter_valid_ips(ip_list):
    def is_valid(ip):
        return int(ip.split(".")[-1]) not in [0, 1, 255]
    return filter(is_valid, ip_list)

def cognate_allocated_ips(cognate_inventory_folder):
    cognate_inventories = glob.glob("{}/*.yml".format(cognate_inventory_folder)) + glob.glob("{}/*.yaml".format(cognate_inventory_folder))
    allocated_ips = []
    for inventory in cognate_inventories:
        inventory_dict = yaml_to_dict(inventory)
        allocated_ips = allocated_ips + [host["ip"] for host in inventory_dict["hosts"]]
    return allocated_ips

def get_free_ips(cognate_ip_range, cognate_inventory_folder, n):
    valid_ip_list = list(filter_valid_ips(ip_range(cognate_ip_range)))
    allocated_ips = cognate_allocated_ips(cognate_inventory_folder)
    ip_candidates = set(valid_ip_list) - set(allocated_ips)
    if len(ip_candidates) >= n:
        return random.sample(ip_candidates, n)
    else:
        return []

def replace_content(input, output, pairs):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(input, 'r') as reader, open(output, 'w') as writer:
        content = reader.read()
        for (k, v) in pairs:
            content = content.replace(k, v)
        writer.write(content)

def build_config_dict(file):
    config = yaml_to_dict(file)
    config["cognate_folder"] = os.path.abspath(os.path.expanduser(config["cognate_folder"]))
    config['cognate_inventory_folder'] = os.path.join(config["cognate_folder"], COGNATE_INVENTORY_PATH)
    config['cognate_provisioning_folder'] = os.path.join(config["cognate_folder"], COGNATE_PROVISIONING_PATH)
    return config

def parse_replacements(items):
    def parse_var(s):
        items = s.split('=')
        key = items[0].strip()
        if len(items) > 1:
            value = '='.join(items[1:])
        return (key, value)
    d = {}
    if items:
        for item in items:
            key, value = parse_var(item)
            d[key] = value
    return d

def allocate_dynamic_ips(cognate_ip_range, cognate_inventory_folder, symbols):
    new_replacement_dict = {}
    dynamic_ips = get_free_ips(cognate_ip_range, cognate_inventory_folder, len(symbols))
    if len(symbols) > 0:
        if len(dynamic_ips) > 0:
            d = {symbol:dynamic_ips[i] for i, symbol in enumerate(symbols)}
            new_replacement_dict.update(d)
        else:
            print("Not enough free IP address(es) to allocate. Please review the config attribute 'cognate_ip_range' in config.yml file.")
            print("Nothing to do.")
            exit(1)
    return new_replacement_dict

def prefix_symbols(prefix, symbols):
    return {symbol:(prefix+symbol.replace("@", "")) for symbol in symbols}

def create_folder(path, overwrite=False):
    if os.path.exists(path):
        if not overwrite:
            print("Folder '{}' exists. Remove it before proceeding or ckeck --overwrite option.".format(path))
            print("Nothing to do.")
            exit(1)
        else:
            shutil.rmtree(path)
    os.makedirs(path)

def list_all_files(path):
    files = []
    for root, d_names, f_names in os.walk(path):
        files = files + [os.path.join(root, f) for f in f_names]
    return files

def apply_changes(source_folder, cognate_inventory_folder, cognate_provisioning_folder, replacement_dict, overwrite=False):
    source_files_realpath = [os.path.realpath(sf) for sf in list_all_files(source_folder)]
    source_folder_realpath = os.path.realpath(source_folder)
    source_files_relativepath = [os.path.relpath(sfr, source_folder_realpath) for sfr in source_files_realpath]
    create_folder(os.path.join(cognate_provisioning_folder, replacement_dict["@cluster_name@"]), overwrite=overwrite)
    for i, sfr in enumerate(source_files_relativepath):
        replace_content(source_files_realpath[i], os.path.join(cognate_provisioning_folder, replacement_dict["@cluster_name@"], sfr), replacement_dict.items())
    shutil.move(os.path.join(cognate_provisioning_folder, replacement_dict["@cluster_name@"], COGNATE_INVENTORY_FILE), os.path.join(cognate_inventory_folder, "{}.yml".format(replacement_dict["@cluster_name@"])))
    shutil.rmtree(os.path.join(cognate_provisioning_folder, replacement_dict["@cluster_name@"], COGNATE_TEMPLATE_SCRIPTS_FOLDER))

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--source-folder",
        metavar="TEMPLATE_FOLDER",
        required=True,
        type=str,
        help="Template folder name")
    parser.add_argument(
        "-c", "--cluster",
        metavar='''CLUSTER_NAME''',
        required=True,
        type=str,
        help='''Cluster name''')
    parser.add_argument(
        "-r", "--replace",
        metavar="@SYMBOL@=VALUE",
        action='append',
        required=False,
        help='''Set a number of keys that are to be replaced by their corresponding
                values (do not put spaces before or after the = sign). If a value 
                contains spaces, you should define it with double quotes:
                    @foo@="this is a sentence"
                Note that values are always treated as strings.''')
    parser.add_argument(
        "--prefix-with-cluster-name",
        metavar="@SYMBOL@",
        action='append',
        required=False,
        type=str,
        help='''Replaces all ocurrences of @SYMBOL@ by <CLUSTER_NAME>__SYMBOL''')
    parser.add_argument(
        "--replace-by-random-ip",
        metavar="@SYMBOL@",
        action='append',
        required=False,
        type=str,
        help='''Replaces all ocurrences of @SYMBOL@ by a random IP''')
    parser.add_argument(
        "--overwrite",
        action='store_true',
        required=False,
        help='''Overwrite all files and folders.
                WARNING: Cluster folder and will be deleted and recreated''')

    return parser

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    config = build_config_dict(CONFIG_FILE)

    if not args.cluster.isidentifier():
        print("Invalid cluster name: {}".format(args.cluster))
        print("Nothing to do")
        exit(1)

    replacement_dict = parse_replacements(args.replace)
    dynamic_ip_dict = allocate_dynamic_ips(config["cognate_ip_range"], config["cognate_inventory_folder"], args.replace_by_random_ip)
    prefix_symbols_dict = prefix_symbols((args.cluster)+"__", args.prefix_with_cluster_name)

    replacements_dict = {}
    replacements_dict.update(replacement_dict)
    replacements_dict.update(dynamic_ip_dict)
    replacements_dict.update(prefix_symbols_dict)
    replacements_dict.update({"@cluster_name@": args.cluster})
    
    apply_changes(args.source_folder, config['cognate_inventory_folder'], config['cognate_provisioning_folder'], replacements_dict, overwrite=args.overwrite)