# sre_guardrails.rego
# OrderFlow SRE Platform — Conftest OPA Rego v1 Guardrails
# Target: openpolicyagent/conftest:latest (OPA v1)
# Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.

package main

import rego.v1

is_openslo_slo if {
  is_object(input)
  object.get(input, "apiVersion", "") == "openslo/v1"
  object.get(input, "kind", "") == "SLO"
}

is_alertmanager_cfg if {
  is_object(input)
  keys := object.keys(input)
  "global" in keys
  "route" in keys
}

is_chaos_fault if {
  is_object(input)
  api := object.get(input, "apiVersion", "")
  startswith(api, "chaos-mesh.org/")
  kind := object.get(input, "kind", "")
  kind in {"NetworkChaos", "PodChaos", "StressChaos"}
}

is_chaos_workflow if {
  is_object(input)
  api := object.get(input, "apiVersion", "")
  startswith(api, "chaos-mesh.org/")
  object.get(input, "kind", "") == "Workflow"
}

has_status_check(templates) if {
  is_array(templates)
  some tmpl in templates
  object.get(tmpl, "templateType", "") == "StatusCheck"
}

# --- Rule 1: OpenSLO v1 SLO Guardrails ---

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  bm := object.get(spec, "budgetingMethod", "")
  not is_string(bm)
  msg := "OPENSLO_BUDGET_METHOD: spec.budgetingMethod must be set"
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  bm := object.get(spec, "budgetingMethod", "")
  is_string(bm)
  trim_space(bm) == ""
  msg := "OPENSLO_BUDGET_METHOD: spec.budgetingMethod must be non-empty"
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  not is_array(objs)
  msg := "OPENSLO_OBJECTIVES: spec.objectives must be an array"
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  is_array(objs)
  count(objs) == 0
  msg := "OPENSLO_OBJECTIVES: spec.objectives must not be empty"
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  is_array(objs)
  some obj in objs
  "target" in object.keys(obj)
  not is_number(obj.target)
  msg := "OPENSLO_TARGET_TYPE: objective target must be numeric ratio"
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  is_array(objs)
  some obj in objs
  "target" in object.keys(obj)
  is_number(obj.target)
  obj.target >= 1
  msg := sprintf(
    "OPENSLO_100_FALLACY: target %v >= 1.0 violates reliability math",
    [obj.target],
  )
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  is_array(objs)
  some obj in objs
  "targetPercent" in object.keys(obj)
  is_number(obj.targetPercent)
  obj.targetPercent >= 100
  msg := sprintf(
    "OPENSLO_100_FALLACY: targetPercent %v >= 100 is invalid",
    [obj.targetPercent],
  )
}

deny contains msg if {
  is_openslo_slo
  spec := object.get(input, "spec", {})
  objs := object.get(spec, "objectives", [])
  is_array(objs)
  some obj in objs
  obj_keys := object.keys(obj)
  not ("target" in obj_keys)
  not ("targetPercent" in obj_keys)
  msg := "OPENSLO_MISSING_TARGET: objective must set target ratio < 1.0"
}

# --- Rule 2: Alertmanager v0.35 Hygiene & Opsgenie Sunset ---

deny contains msg if {
  is_alertmanager_cfg
  route := object.get(input, "route", {})
  gb := object.get(route, "group_by", [])
  not is_array(gb)
  msg := "AM_GROUP_BY: route.group_by must be a non-empty list"
}

deny contains msg if {
  is_alertmanager_cfg
  route := object.get(input, "route", {})
  gb := object.get(route, "group_by", [])
  is_array(gb)
  count(gb) == 0
  msg := "AM_GROUP_BY: route.group_by must not be empty"
}

deny contains msg if {
  is_alertmanager_cfg
  inh := object.get(input, "inhibit_rules", [])
  not is_array(inh)
  msg := "AM_INHIBIT_RULES: inhibit_rules must be a non-empty list"
}

deny contains msg if {
  is_alertmanager_cfg
  inh := object.get(input, "inhibit_rules", [])
  is_array(inh)
  count(inh) == 0
  msg := "AM_INHIBIT_RULES: define at least one inhibit_rule"
}

deny contains msg if {
  is_alertmanager_cfg
  recvs := object.get(input, "receivers", [])
  is_array(recvs)
  some recv in recvs
  "opsgenie_configs" in object.keys(recv)
  name := object.get(recv, "name", "unknown")
  msg := sprintf(
    "OPSGENIE_SUNSET: receiver %q uses banned opsgenie_configs (2027)",
    [name],
  )
}

# --- Rule 3: Chaos Mesh v2.8 Blast-Radius & StatusCheck Guards ---

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  sel := object.get(spec, "selector", {})
  ns := object.get(sel, "namespaces", [])
  not is_array(ns)
  msg := "CHAOS_NAMESPACES: spec.selector.namespaces must be an array"
}

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  sel := object.get(spec, "selector", {})
  ns := object.get(sel, "namespaces", [])
  is_array(ns)
  count(ns) == 0
  msg := "CHAOS_NAMESPACES: spec.selector.namespaces must be non-empty"
}

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  sel := object.get(spec, "selector", {})
  ns := object.get(sel, "namespaces", [])
  is_array(ns)
  some item in ns
  item == "kube-system"
  msg := "CHAOS_KUBE_SYSTEM: never target kube-system in Chaos Mesh"
}

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  dur := object.get(spec, "duration", "")
  not is_string(dur)
  msg := "CHAOS_DURATION: spec.duration must be an explicit string"
}

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  dur := object.get(spec, "duration", "")
  is_string(dur)
  trim_space(dur) == ""
  msg := "CHAOS_DURATION: spec.duration must not be empty"
}

deny contains msg if {
  is_chaos_fault
  spec := object.get(input, "spec", {})
  object.get(spec, "mode", "") == "all"
  msg := "CHAOS_BLAST_RADIUS: spec.mode \"all\" is banned; scope targets"
}

deny contains msg if {
  is_chaos_workflow
  spec := object.get(input, "spec", {})
  tmpls := object.get(spec, "templates", [])
  not has_status_check(tmpls)
  msg := "CHAOS_ABORT_GUARD: Workflow requires a StatusCheck template"
}
