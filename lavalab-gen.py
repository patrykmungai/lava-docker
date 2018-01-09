#!/usr/bin/env python
#
from __future__ import print_function
import os, sys, time
import subprocess
import argparse
import yaml
import string
import socket
import shutil

# Defaults
boards_yaml = "boards.yaml"
tokens_yaml = "tokens.yaml"
baud_default = 115200
    
template = string.Template("""#
# auto-generated by lavalab-gen.py for ${board}
#
listener ${board}
application console '${board} console' 'exec sg dialout "cu-loop /dev/${board} ${baud}"'
command 'hardreset' 'Reboot ${board}' 'pduclient --daemon ${daemon} --host ${host} --port ${port} --command reboot ${delay} '
command 'b' 'Reboot ${board}' 'pduclient --daemon ${daemon} --host ${host} --port ${port} --command reboot '
command 'off' 'Power off ${board}' 'pduclient --daemon ${daemon} --host ${host} --port ${port} --command off '
command 'on' 'Power on ${board}' 'pduclient --daemon ${daemon} --host ${host} --port ${port} --command on '
""")

#no comment it is volontary
template_device = string.Template("""{% extends '${devicetype}.jinja2' %}
{% set connection_command = 'conmux-console ${board}' %}
{% set hard_reset_command = 'pduclient --daemon localhost --hostname acme-0 --port ${port} --command=reboot' %}
{% set power_off_command = 'pduclient --daemon localhost --hostname acme-0 --port ${port} --command=off' %}
{% set power_on_command = 'pduclient --daemon localhost --hostname acme-0 --port ${port} --command=on' %}
""")

template_udev = string.Template("""#
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="${serial}", MODE="0664", OWNER="uucp", SYMLINK+="${board}"
""")

def main(args):
    fp = open(boards_yaml, "r")
    labs = yaml.load(fp)
    fp.close()
    udev_line =""
    tdc = open("docker-compose.template", "r")
    dockcomp = yaml.load(tdc)
    tdc.close()
    dc_devices = dockcomp["services"]["lava-slave"]["devices"]
    if dc_devices is None:
        dockcomp["services"]["lava-slave"]["devices"] = []
        dc_devices = dockcomp["services"]["lava-slave"]["devices"]

    # The slaves directory must exists
    if not os.path.isdir("lava-master/slaves/"):
        os.mkdir("lava-master/slaves/")
        fp = open("lava-master/slaves/.empty", "w")
        fp.close()
    if not os.path.isdir("lava-slave/conmux/"):
        os.mkdir("lava-slave/conmux/")
        fp = open("lava-slave/conmux/.empty", "w")
        fp.close()

    for lab_name in labs:
        lab = labs[lab_name]
        for board_name in lab["boardlist"]:
            b = lab["boardlist"][board_name]
            if b.get("disabled", None):
                continue

            if not b.has_key("uart"):
                print("WARNING: %s missing uart property" % board_name)
                continue

            baud = b["uart"].get("baud", baud_default)
            if b.has_key("pdu"):
                daemon = b["pdu"]["daemon"]
                host = b["pdu"]["host"]
                port = b["pdu"]["port"]
                devicetype = b["type"]
                delay_opt = ""
                line = template.substitute(board=board_name, baud=baud, daemon=daemon, host=host, port=port, delay=delay_opt)
                device_line = template_device.substitute(board=board_name, port=port, devicetype=devicetype)
                serial = b["uart"]["serial"]
                udev_line += template_udev.substitute(board=board_name, serial=serial)
                dc_devices.append("/dev/%s:/dev/%s" % (board_name, board_name))
            if b.has_key("fastboot_serial_number"):
                fserial = b["fastboot_serial_number"]
                device_line += "{%% set fastboot_serial_number = '%s' %%}" % fserial

            # board specific hacks
            if devicetype == "qemu":
                device_line += "{% set no_kvm = True %}\n"
            if not os.path.isdir("lava-master/devices/"):
                os.mkdir("lava-master/devices/")
            device_path = "lava-master/devices/%s" % lab_name
            if not os.path.isdir(device_path):
                os.mkdir(device_path)
            fp = open("lava-slave/conmux/%s.cf" % board_name, "w")
            fp.write(line)
            fp.close()
            board_device_file = "%s/%s.jinja2" % (device_path, board_name)
            fp = open(board_device_file, "w")
            fp.write(device_line)
            fp.close()
        fp = open("lavalab-udev-%s.rules" % lab_name, "w")
        fp.write(udev_line)
        fp.close()
        if lab.has_key("dispatcher_ip"):
            fp = open("lava-master/slaves/%s.yaml" % lab_name, "w")
            fp.write("dispatcher_ip: %s" % lab["dispatcher_ip"])
            fp.close()

    #now proceed with tokens
    fp = open(tokens_yaml, "r")
    tokens = yaml.load(fp)
    fp.close()
    if not os.path.isdir("lava-master/users/"):
        os.mkdir("lava-master/users/")
    if not os.path.isdir("lava-master/tokens/"):
        os.mkdir("lava-master/tokens/")
    for section_name in tokens:
        section = tokens[section_name]
        if section_name == "lava_server_users":
            for user in section:
                username = user["name"]
                ftok = open("lava-master/users/%s" % username, "w")
                token = user["token"]
                ftok.write("TOKEN=" + token + "\n")
                if user.has_key("password"):
                    password = user["password"]
                    ftok.write("PASSWORD=" + password + "\n")
                # libyaml convert yes/no to true/false...
                if user.has_key("staff"):
                    value = user["staff"]
                    if value is True:
                        ftok.write("STAFF=1\n")
                if user.has_key("superuser"):
                    value = user["superuser"]
                    if value is True:
                        ftok.write("SUPERUSER=1\n")
                ftok.close()
        if section_name == "callback_tokens":
            for token in section:
                filename = token["filename"]
                ftok = open("lava-master/tokens/%s" % filename, "w")
                username = token["username"]
                ftok.write("USER=" + username + "\n")
                vtoken = token["token"]
                ftok.write("TOKEN=" + vtoken + "\n")
                description = token["description"]
                ftok.write("DESCRIPTION=" + description)
                ftok.close()
    with file('docker-compose.yml', 'w') as f:
        yaml.dump(dockcomp, f)

if __name__ == "__main__":
    shutil.copy("common/build-lava", "lava-slave/scripts/build-lava")
    shutil.copy("common/build-lava", "lava-master/scripts/build-lava")
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", help="use this file as header for output file")
    args = parser.parse_args()
    main(args)

