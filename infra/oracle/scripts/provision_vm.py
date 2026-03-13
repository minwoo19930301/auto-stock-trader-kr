#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import oci
from oci.pagination import list_call_get_all_results


VCN_NAME = os.getenv("OCI_VCN_NAME", "stock-broker-vcn")
SUBNET_NAME = os.getenv("OCI_SUBNET_NAME", "stock-broker-public-subnet")
IGW_NAME = os.getenv("OCI_IGW_NAME", "stock-broker-igw")
INSTANCE_NAME = os.getenv("OCI_INSTANCE_NAME", "stock-broker-api-vm")
CIDR_BLOCK = os.getenv("OCI_VCN_CIDR", "10.0.0.0/16")
SUBNET_CIDR = os.getenv("OCI_SUBNET_CIDR", "10.0.0.0/24")
SHAPE_PREFERENCE = os.getenv("OCI_SHAPE_PREFERENCE", "VM.Standard.A1.Flex,VM.Standard.E2.1.Micro").split(",")
SSH_PUBLIC_KEY_PATH = os.getenv("OCI_SSH_PUBLIC_KEY_PATH", str(Path.home() / ".ssh" / "id_rsa.pub"))
STATE_DIR = Path(os.getenv("OCI_STATE_DIR", ".deploy/oracle"))
STATE_FILE = STATE_DIR / "instance.json"


def load_config() -> dict:
    return oci.config.from_file()


def pick_ssh_public_key() -> str:
    candidates = [
        Path(SSH_PUBLIC_KEY_PATH),
        Path.home() / ".ssh" / "id_ed25519.pub",
        Path.home() / ".ssh" / "id_rsa.pub",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text().strip()
    raise FileNotFoundError("No SSH public key found")


def find_by_name(items, name: str):
    for item in items:
        if getattr(item, "display_name", None) == name:
            return item
    return None


def ensure_vcn(network_client, compartment_id: str):
    vcns = list_call_get_all_results(network_client.list_vcns, compartment_id).data
    existing = find_by_name(vcns, VCN_NAME)
    if existing:
        return existing

    details = oci.core.models.CreateVcnDetails(
        cidr_block=CIDR_BLOCK,
        compartment_id=compartment_id,
        display_name=VCN_NAME,
        dns_label="stockvcn",
    )
    vcn = network_client.create_vcn(details).data
    oci.wait_until(network_client, network_client.get_vcn(vcn.id), "lifecycle_state", "AVAILABLE")
    return network_client.get_vcn(vcn.id).data


def ensure_internet_gateway(network_client, compartment_id: str, vcn_id: str):
    igws = list_call_get_all_results(network_client.list_internet_gateways, compartment_id, vcn_id=vcn_id).data
    existing = find_by_name(igws, IGW_NAME)
    if existing:
        return existing

    details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        display_name=IGW_NAME,
        is_enabled=True,
        vcn_id=vcn_id,
    )
    igw = network_client.create_internet_gateway(details).data
    oci.wait_until(network_client, network_client.get_internet_gateway(igw.id), "lifecycle_state", "AVAILABLE")
    return network_client.get_internet_gateway(igw.id).data


def ensure_route(network_client, route_table_id: str, igw_id: str):
    route_table = network_client.get_route_table(route_table_id).data
    rules = route_table.route_rules or []
    if not any(rule.network_entity_id == igw_id and rule.destination == "0.0.0.0/0" for rule in rules):
        rules.append(
            oci.core.models.RouteRule(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=igw_id,
            )
        )
        network_client.update_route_table(
            route_table_id,
            oci.core.models.UpdateRouteTableDetails(route_rules=rules),
        )


def ensure_security_rules(network_client, security_list_id: str):
    security_list = network_client.get_security_list(security_list_id).data
    ingress_rules = security_list.ingress_security_rules or []
    existing_ports = set()
    for rule in ingress_rules:
        if rule.source == "0.0.0.0/0" and rule.protocol == "6" and rule.tcp_options:
            existing_ports.add((rule.tcp_options.destination_port_range.min, rule.tcp_options.destination_port_range.max))

    for port in (22, 80, 443):
        if (port, port) not in existing_ports:
            ingress_rules.append(
                oci.core.models.IngressSecurityRule(
                    protocol="6",
                    source="0.0.0.0/0",
                    tcp_options=oci.core.models.TcpOptions(
                        destination_port_range=oci.core.models.PortRange(min=port, max=port)
                    ),
                )
            )

    egress_rules = security_list.egress_security_rules or []
    if not any(rule.destination == "0.0.0.0/0" for rule in egress_rules):
        egress_rules.append(
            oci.core.models.EgressSecurityRule(
                protocol="all",
                destination="0.0.0.0/0",
            )
        )

    network_client.update_security_list(
        security_list_id,
        oci.core.models.UpdateSecurityListDetails(
            ingress_security_rules=ingress_rules,
            egress_security_rules=egress_rules,
        ),
    )


def ensure_subnet(network_client, compartment_id: str, availability_domain: str, vcn):
    subnets = list_call_get_all_results(network_client.list_subnets, compartment_id, vcn_id=vcn.id).data
    existing = find_by_name(subnets, SUBNET_NAME)
    if existing:
        return existing

    details = oci.core.models.CreateSubnetDetails(
        availability_domain=availability_domain,
        cidr_block=SUBNET_CIDR,
        compartment_id=compartment_id,
        display_name=SUBNET_NAME,
        dns_label="publicsub",
        prohibit_public_ip_on_vnic=False,
        route_table_id=vcn.default_route_table_id,
        security_list_ids=[vcn.default_security_list_id],
        vcn_id=vcn.id,
    )
    subnet = network_client.create_subnet(details).data
    oci.wait_until(network_client, network_client.get_subnet(subnet.id), "lifecycle_state", "AVAILABLE")
    return network_client.get_subnet(subnet.id).data


def available_shapes(compute_client, compartment_id: str, availability_domain: str):
    shapes = list_call_get_all_results(compute_client.list_shapes, compartment_id, availability_domain=availability_domain).data
    return {shape.shape: shape for shape in shapes}


def select_image(compute_client, compartment_id: str, want_aarch64: bool):
    images = list_call_get_all_results(compute_client.list_images, compartment_id).data
    matches = []
    for image in images:
        name = image.display_name or ""
        os_name = image.operating_system or ""
        if "Canonical Ubuntu" not in os_name:
            continue
        if "24.04" not in name:
            continue
        if want_aarch64 and "aarch64" not in name:
            continue
        if not want_aarch64 and "aarch64" in name:
            continue
        if "Minimal" in name:
            continue
        matches.append(image)

    if not matches:
        raise RuntimeError("No matching Ubuntu image found")

    matches.sort(key=lambda item: item.display_name, reverse=True)
    return matches[0]


def ensure_instance(compute_client, network_client, compartment_id: str, availability_domain: str, subnet_id: str):
    instances = list_call_get_all_results(compute_client.list_instances, compartment_id).data
    existing = find_by_name(instances, INSTANCE_NAME)
    if existing and existing.lifecycle_state not in {"TERMINATED", "TERMINATING"}:
        if existing.lifecycle_state != "RUNNING":
            oci.wait_until(compute_client, compute_client.get_instance(existing.id), "lifecycle_state", "RUNNING")
        return compute_client.get_instance(existing.id).data

    shape_map = available_shapes(compute_client, compartment_id, availability_domain)
    ssh_public_key = pick_ssh_public_key()
    last_error = None

    for preferred_shape_name in SHAPE_PREFERENCE:
        shape = shape_map.get(preferred_shape_name)
        if shape is None:
            continue

        want_aarch64 = shape.shape == "VM.Standard.A1.Flex"
        image = select_image(compute_client, compartment_id, want_aarch64)

        launch_details = oci.core.models.LaunchInstanceDetails(
            availability_domain=availability_domain,
            compartment_id=compartment_id,
            display_name=INSTANCE_NAME,
            shape=shape.shape,
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=True,
            ),
            metadata={"ssh_authorized_keys": ssh_public_key},
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=image.id,
                source_type="image",
            ),
        )

        if shape.shape == "VM.Standard.A1.Flex":
            launch_details.shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=1.0,
                memory_in_gbs=6.0,
            )

        try:
            instance = compute_client.launch_instance(launch_details).data
            oci.wait_until(
                compute_client,
                compute_client.get_instance(instance.id),
                "lifecycle_state",
                "RUNNING",
                max_wait_seconds=1800,
            )
            return compute_client.get_instance(instance.id).data
        except oci.exceptions.ServiceError as error:
            last_error = error
            if error.code == "InternalError" and "Out of host capacity" in str(error.message):
                time.sleep(2)
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("No preferred shape found")


def get_public_ip(compute_client, network_client, compartment_id: str, instance_id: str) -> str | None:
    attachments = list_call_get_all_results(
        compute_client.list_vnic_attachments,
        compartment_id=compartment_id,
        instance_id=instance_id,
    ).data
    if not attachments:
        return None
    vnic = network_client.get_vnic(attachments[0].vnic_id).data
    return vnic.public_ip


def main():
    config = load_config()
    compartment_id = config["tenancy"]
    identity_client = oci.identity.IdentityClient(config)
    compute_client = oci.core.ComputeClient(config)
    network_client = oci.core.VirtualNetworkClient(config)

    availability_domain = identity_client.list_availability_domains(compartment_id=compartment_id).data[0].name
    vcn = ensure_vcn(network_client, compartment_id)
    igw = ensure_internet_gateway(network_client, compartment_id, vcn.id)
    ensure_route(network_client, vcn.default_route_table_id, igw.id)
    ensure_security_rules(network_client, vcn.default_security_list_id)
    subnet = ensure_subnet(network_client, compartment_id, availability_domain, vcn)
    instance = ensure_instance(compute_client, network_client, compartment_id, availability_domain, subnet.id)
    public_ip = get_public_ip(compute_client, network_client, compartment_id, instance.id)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "region": config["region"],
                "availability_domain": availability_domain,
                "vcn_id": vcn.id,
                "subnet_id": subnet.id,
                "internet_gateway_id": igw.id,
                "instance_id": instance.id,
                "shape": instance.shape,
                "public_ip": public_ip,
            },
            indent=2,
        )
    )

    print(json.dumps(json.loads(STATE_FILE.read_text()), indent=2))


if __name__ == "__main__":
    main()
