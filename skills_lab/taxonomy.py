"""IT skill categories used to tag logbook entries.

Edit freely: add a category, change the wording, or add keywords. Everything else (classifier, evaluation,
report) reads from here. The `description` is what the Hugging Face zero-shot backends compare entries against,
and the `keywords` feed the offline keyword baseline. Written for this project, not copied from SFIA / ESCO
(those are licensed); you can map categories to them later if your institution requires it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    description: str
    keywords: dict[str, float] = field(default_factory=dict)  # word or phrase -> weight (default 1.0)


def _kw(text: str, weak: str = "") -> dict[str, float]:
    out = {w.strip().lower(): 1.0 for w in text.split(",") if w.strip()}
    out.update({w.strip().lower(): 0.5 for w in weak.split(",") if w.strip()})
    return out


CATEGORIES: tuple[Category, ...] = (
    Category("networking", "Networking",
             "Setting up, cabling, configuring and maintaining computer networks: routers, switches, Wi-Fi, IP addressing, "
             "DNS, DHCP, VLANs, VPNs and network devices.",
             _kw("router, routers, switch, switches, wifi, wi-fi, wireless, access point, lan, wan, vlan, vpn, subnet, "
                 "subnetting, ip address, ip addresses, static ip, dhcp, dns, rj45, cat6, cat5, ethernet, patch panel, "
                 "patch cable, patch cables, patch leads, port forwarding, network, networks, cabling, crimped, crimping, "
                 "tp-link, mikrotik, cisco, ubiquiti, gateway, bandwidth, topology, osi, tcp/ip, ports, "
                 "wlan, fibre, fiber",
                 weak="cable, cables, port")),
    Category("troubleshooting", "Troubleshooting & Technical Support",
             "Diagnosing and fixing faults, answering helpdesk calls and tickets, and supporting users with their "
             "computers, printers, email and software problems.",
             _kw("troubleshoot, troubleshot, troubleshooting, diagnosed, diagnose, diagnosing, helpdesk, help desk, "
                 "ticket, tickets, fault, faults, faulty, resolved, fixed, fix, repaired, not working, would not, could not, "
                 "kept restarting, kept crashing, frozen, freezing, slow computer, very slow, error message, remote desktop, "
                 "teamviewer, anydesk, user support, support calls, escalated, root cause, not printing, "
                 "blank screen, will not boot, no internet, rekebisha, nilirekebisha, tatizo",
                 weak="issue, problem, problems, complained, checked")),
    Category("hardware", "Hardware & Devices",
             "Assembling, installing, upgrading, repairing and testing computers and devices: desktops, laptops, "
             "printers, scanners, CCTV, point-of-sale equipment, UPS units and projectors.",
             _kw("assembled, assembling, motherboard, ram, ssd, hard drive, hard disk, power supply, psu, cpu, processor, "
                 "thermal paste, laptop screen, keyboard, mouse, monitor, printer, printers, scanner, projector, cctv, "
                 "dvr, camera, cameras, ups, battery, batteries, pos terminal, point of sale, barcode, receipt printer, "
                 "biometric, desktop computers, workstations, peripherals, toner, cartridge, dust, casing, "
                 "",
                 weak="installed, replaced, device, devices, upgraded")),
    Category("os_admin", "Operating Systems & Administration",
             "Installing and administering operating systems and servers: Windows, Linux, user accounts, Active "
             "Directory, group policy, updates, imaging, file shares and backups.",
             _kw("windows, windows 10, windows 11, windows server, linux, ubuntu, mint, debian, centos, active directory, "
                 "group policy, gpo, user account, user accounts, domain controller, powershell, bash, command line, "
                 "chmod, grep, sudo, disk image, imaging, clone, cloned, deploy, deployed, updates, patches, file server, "
                 "shared folder, network drive, mapped, permissions, quota, quotas, dual boot, dual-booted, os, "
                 "operating system, installed windows, ",
                 weak="installed, installation, software, account")),
    Category("security", "Cybersecurity",
             "Protecting systems and data: antivirus, firewalls, passwords, access control, encryption, phishing "
             "awareness, patching vulnerabilities and data protection.",
             _kw("antivirus, anti-virus, malware, virus, trojan, ransomware, firewall, phishing, suspicious email, "
                 "password, passwords, two-factor, 2fa, mfa, multi-factor, encrypt, encrypted, encryption, bitlocker, "
                 "access rights, access control, authorised, authorized, vulnerability, vulnerabilities, "
                 "open ports, port scan, data protection, confidential, security, secure, "
                 "default passwords, ssl, certificate",
                 weak="scan, blocked, policy")),
    Category("databases", "Databases & Data",
             "Working with databases and data: SQL queries, table design, data entry and cleaning, spreadsheets, "
             "reports, imports and exports, and database backups.",
             _kw("sql, mysql, postgresql, postgres, sqlite, oracle, database, databases, query, queries, stored procedure, "
                 "tables, primary key, normalised, normalized, normalisation, data entry, records, "
                 "duplicates, excel, spreadsheet, spreadsheets, pivot, formulas, vlookup, access form, ms access, "
                 "import, imported, export, exported, data cleaning, validated, ",
                 weak="data, figures, report")),
    Category("software_web", "Software & Web Development",
             "Writing, testing and debugging code and building websites or applications: Python, JavaScript, PHP, "
             "HTML/CSS, APIs, version control and app interfaces.",
             _kw("python, javascript, java, php, html, css, c#, c++, react, flask, django, laravel, node, api, rest, "
                 "endpoint, code, coding, coded, script, scripts, program, programming, bug, bugs, debug, debugged, "
                 "debugging, git, github, commit, merge conflicts, website, web page, webpage, landing page, wordpress, "
                 "plugin, android, app, application development, function, functions, login form, "
                 "figma, user interface, responsive, frontend, backend, web app, payment api, ",
                 weak="developed, website, web")),
    Category("cloud", "Cloud & Virtualisation",
             "Using virtual machines and cloud services: Hyper-V, VirtualBox, VMware, AWS, Azure, Google Workspace, "
             "Microsoft 365, hosting, domains and cloud backup.",
             _kw("virtual machine, virtual machines, vm, vms, hyper-v, virtualbox, vmware, virtualisation, virtualization, "
                 "aws, ec2, azure, google cloud, gcp, cloud, digitalocean, microsoft 365, office 365, m365, google "
                 "workspace, g suite, google drive, onedrive, sharepoint, shared mailbox, mailbox, mailboxes, hosting, "
                 "web hosting, domain name, domain, snapshot, snapshots, nginx, virtual server, "
                 "dns record, ssl certificate",
                 weak="server, email")),
    Category("docs_comms", "Documentation & Communication",
             "Writing and presenting technical information: user guides, procedures, reports, network diagrams, "
             "asset registers, training users and taking minutes.",
             _kw("user guide, manual, procedure, procedures, sop, standard operating procedure, documented, documentation, "
                 "document the steps, wrote a guide, prepared a report, weekly report, summary, summarising, summarizing, "
                 "presented, presentation, powerpoint, slides, minutes, meeting, trained, training, explained, explain, "
                 "diagram, visio, wrote, emailed, "
                 "intranet, ",
                 weak="report, prepared, compiled")),
    Category("professional", "Professional Practice",
             "Workplace skills: teamwork, time management, customer care, safety, ethics, taking feedback, planning "
             "and observing how projects and departments are run.",
             _kw("team, teamwork, deadline, deadlines, time management, prioritise, prioritize, customer, customers, "
                 "client, clients, politely, professional, professionally, safety, safe, ladder, ladders, induction, "
                 "policies, dress code, supervisor, feedback, observed, delegate, delegated, "
                 "project plan, budget, timeline, punctual, initiative, "
                 "ethics, attitude, ",
                 weak="learnt, learned, worked with")),
)

BY_KEY = {c.key: c for c in CATEGORIES}
KEYS = tuple(c.key for c in CATEGORIES)
