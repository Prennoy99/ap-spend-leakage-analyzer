"""Builds docs/bpmn/to_be_invoice_to_pay.bpmn: the to-be invoice-to-pay process (Improve, task 5.3).

The model is written as data (lanes, nodes on a column grid, flows, annotations)
and turned into BPMN 2.0 XML with diagram coordinates, so it opens in Camunda
Modeler and at demo.bpmn.io. Lanes are roles or the ERP, never people.

Run: python scripts/build_to_be_bpmn.py docs/bpmn/to_be_invoice_to_pay.bpmn
"""

import sys
from xml.sax.saxutils import escape

# --- The model ------------------------------------------------------------------

LANES = [  # (id, name, height)
    ("Lane_ERP", "ERP (automated)", 190),
    ("Lane_APClerk", "AP clerk", 150),
    ("Lane_BudgetOwner", "Budget owner", 170),
    ("Lane_APManager", "AP Manager", 150),
    ("Lane_Treasury", "Treasury", 130),
    ("Lane_Controlling", "Controlling", 130),
]

# id: (bpmn type, name, lane, column, extra attributes)
NODES = {
    "Start_InvoiceReceived": ("startEvent:message", "Invoice received", "Lane_ERP", 0),
    "Task_Capture": ("serviceTask", "Capture invoice data (e-invoice import; RPA bot reads PDFs)", "Lane_ERP", 1),
    "Task_Validate": ("serviceTask", "Validate at entry: supplier, cost centre, PO or exception reason", "Lane_ERP", 2),
    "Gateway_EntryOK": ("exclusiveGateway", "Entry data complete?", "Lane_ERP", 3),
    "Task_Clarify": ("userTask", "Complete data with requester or supplier", "Lane_APClerk", 3),
    "Task_DuplicateCheck": ("serviceTask", "Duplicate check: PO already invoiced, or same supplier and amount within 5 days",
                            "Lane_ERP", 4),
    "Gateway_Duplicate": ("exclusiveGateway", "Suspected duplicate?", "Lane_ERP", 5),
    "Task_ReviewDuplicate": ("userTask", "Review the flag: reject the copy, tell the supplier", "Lane_APClerk", 5),
    "End_DuplicateStopped": ("endEvent", "Duplicate stopped before payment", "Lane_APClerk", 6),
    "Gateway_POInvoice": ("exclusiveGateway", "PO invoice?", "Lane_ERP", 7),
    "Task_ThreeWayMatch": ("serviceTask", "Three-way match: PO, goods receipt, invoice", "Lane_ERP", 8),
    "Gateway_Match": ("exclusiveGateway", "Within tolerance?", "Lane_ERP", 9),
    "Task_AutoApprove": ("serviceTask", "Approve automatically (approved when the PO was released)", "Lane_ERP", 10),
    "Task_Approve": ("userTask", "Review and approve, remaining budget shown", "Lane_BudgetOwner", 10),
    "Timer_ApprovalDeadline": ("boundaryEvent:timer", "2 days before the discount date", "Lane_BudgetOwner", 10),
    "Task_Escalate": ("userTask", "Chase the overdue approval", "Lane_APManager", 10),
    "End_Chased": ("endEvent", "Approval chased", "Lane_APManager", 11),
    "Gateway_Approved": ("exclusiveGateway", "Approved?", "Lane_BudgetOwner", 11),
    "Task_Correct": ("userTask", "Correct invoice or query supplier", "Lane_APClerk", 11),
    "Gateway_MergeApproved": ("exclusiveGateway", "", "Lane_ERP", 12),
    "Task_Schedule": ("serviceTask", "Schedule payment: discount date if offered, else due date", "Lane_ERP", 13),
    "Timer_DailyRun": ("intermediateCatchEvent:timer", "Daily payment run", "Lane_ERP", 14),
    "Task_Proposal": ("serviceTask", "Create payment proposal: due today and approved only", "Lane_ERP", 15),
    "Task_Release": ("userTask", "Release payment proposal", "Lane_APManager", 16),
    "Task_Transfer": ("task", "Execute bank transfer", "Lane_Treasury", 17),
    "Task_Post": ("serviceTask", "Post payment and clear invoice", "Lane_ERP", 18),
    "End_Paid": ("endEvent", "Invoice paid on terms", "Lane_ERP", 19),
    "Start_Weekly": ("startEvent:timer", "Every Monday", "Lane_Controlling", 0),
    "Task_BudgetReview": ("userTask", "Review budget vs actual (live view)", "Lane_Controlling", 1),
    "End_BudgetActed": ("endEvent", "Overruns handled before month-end", "Lane_Controlling", 2),
}

BOUNDARY = {"Timer_ApprovalDeadline": ("Task_Approve", False)}  # attached to, interrupting?

# (id, source, target, name, route) — route picks the waypoint shape, see waypoints().
FLOWS = [
    ("Flow_01", "Start_InvoiceReceived", "Task_Capture", "", "auto"),
    ("Flow_02", "Task_Capture", "Task_Validate", "", "auto"),
    ("Flow_03", "Task_Validate", "Gateway_EntryOK", "", "auto"),
    ("Flow_04", "Gateway_EntryOK", "Task_DuplicateCheck", "Yes", "auto"),
    ("Flow_05", "Gateway_EntryOK", "Task_Clarify", "No", "down"),
    ("Flow_06", "Task_Clarify", "Task_Validate", "", "back_up"),
    ("Flow_07", "Task_DuplicateCheck", "Gateway_Duplicate", "", "auto"),
    ("Flow_08", "Gateway_Duplicate", "Task_ReviewDuplicate", "Yes", "down"),
    ("Flow_09", "Task_ReviewDuplicate", "End_DuplicateStopped", "", "auto"),
    ("Flow_10", "Gateway_Duplicate", "Gateway_POInvoice", "No", "auto"),
    ("Flow_11", "Gateway_POInvoice", "Task_ThreeWayMatch", "Yes", "auto"),
    ("Flow_12", "Gateway_POInvoice", "Task_Approve", "No: exception", "gateway_down"),
    ("Flow_13", "Task_ThreeWayMatch", "Gateway_Match", "", "auto"),
    ("Flow_14", "Gateway_Match", "Task_AutoApprove", "Yes", "auto"),
    ("Flow_15", "Gateway_Match", "Task_Approve", "No", "gateway_down"),
    ("Flow_16", "Task_AutoApprove", "Gateway_MergeApproved", "", "auto"),
    ("Flow_17", "Task_Approve", "Gateway_Approved", "", "auto"),
    ("Flow_18", "Gateway_Approved", "Gateway_MergeApproved", "Yes", "right_up"),
    ("Flow_19", "Gateway_Approved", "Task_Correct", "No", "up"),
    ("Flow_20", "Task_Correct", "Task_Approve", "", "back_down"),
    ("Flow_21", "Timer_ApprovalDeadline", "Task_Escalate", "", "down"),
    ("Flow_22", "Task_Escalate", "End_Chased", "", "auto"),
    ("Flow_23", "Gateway_MergeApproved", "Task_Schedule", "", "auto"),
    ("Flow_24", "Task_Schedule", "Timer_DailyRun", "", "auto"),
    ("Flow_25", "Timer_DailyRun", "Task_Proposal", "", "auto"),
    ("Flow_26", "Task_Proposal", "Task_Release", "", "auto"),
    ("Flow_27", "Task_Release", "Task_Transfer", "", "auto"),
    ("Flow_28", "Task_Transfer", "Task_Post", "", "auto"),
    ("Flow_29", "Task_Post", "End_Paid", "", "auto"),
    ("Flow_30", "Start_Weekly", "Task_BudgetReview", "", "auto"),
    ("Flow_31", "Task_BudgetReview", "End_BudgetActed", "", "auto"),
]

MESSAGES = [  # (id, source, target, name)
    ("Msg_Invoice", "Participant_Supplier", "Start_InvoiceReceived", "Invoice (e-invoice or PDF)"),
    ("Msg_DuplicateNotice", "Task_ReviewDuplicate", "Participant_Supplier", "Duplicate notice"),
    ("Msg_Payment", "Task_Transfer", "Participant_Supplier", "Payment"),
]

# Changes against the as-is model: fix number from the business case, € and hypothesis.
ANNOTATIONS = [  # (id, attached to, text, dx, dy) — offset of the note from the node's top-left
    ("Note_Capture", "Task_Capture",
     "NEW · RPA bot (e.g. UiPath) reads PDF invoices; e-invoices (XRechnung, ZUGFeRD) are imported. "
     "Designed and costed, not built", -40, -150),
    ("Note_Validate", "Task_Validate",
     "FIX 4 · Stops wrong cost centres and missing POs: 55% of today's rejections (D1)", 0, -150),
    ("Note_Duplicate", "Task_DuplicateCheck",
     "FIX 1 · Would have stopped 46 of 50 duplicates, €57.7k a year, before payment (A1)", 0, -150),
    ("Note_ThreeWay", "Task_ThreeWayMatch",
     "NEW · PO, goods receipt and invoice must agree. Covers A2 once PO prices are in the ERP", 0, -150),
    ("Note_AutoApprove", "Task_AutoApprove",
     "NEW · No second approval for matched PO invoices: the budget owner approved the PO", 0, -150),
    ("Note_Approve", "Task_Approve",
     "FIX 3 · Deadline 2 days before the discount date; remaining budget shown (B1, B2, C1)", -270, 175),
    ("Note_Schedule", "Task_Schedule",
     "FIX 2 · Pay to terms (B3): discounts on the last discount day, the rest on the due date", 0, -150),
    ("Note_Proposal", "Task_Proposal",
     "NEW · Payment block: no payment without a recorded approval (13 breaches today)", 0, -150),
    ("Note_Budget", "End_BudgetActed",
     "NEW · Weekly live view: overruns approved or stopped before month-end, not found after it (C1)", 90, -12),
]

# --- Layout ---------------------------------------------------------------------

POOL_X, LANE_X = 160, 190
COLUMN_WIDTH, FIRST_COLUMN_X = 160, 250
SUPPLIER_Y, SUPPLIER_HEIGHT = 0, 60
POOL_Y = 230  # leaves room for the annotations between the supplier pool and the ERP lane
NOTE_Y, NOTE_WIDTH, NOTE_HEIGHT = 85, 150, 110
SIZES = {"task": (130, 90), "gateway": (50, 50), "event": (36, 36)}


def kind(bpmn_type: str) -> str:
    base = bpmn_type.split(":")[0]
    if base.endswith("Gateway"):
        return "gateway"
    if base.endswith("Event"):
        return "event"
    return "task"


def lane_bounds() -> dict:
    bounds, y = {}, POOL_Y
    for lane_id, _, height in LANES:
        bounds[lane_id] = (LANE_X, y, pool_width() - (LANE_X - POOL_X), height)
        y += height
    return bounds


def pool_width() -> int:
    columns = max(node[3] for node in NODES.values()) + 1
    return FIRST_COLUMN_X - POOL_X + columns * COLUMN_WIDTH + 20


def node_bounds() -> dict:
    lanes, bounds = lane_bounds(), {}
    for node_id, (bpmn_type, _, lane, column) in NODES.items():
        if node_id in BOUNDARY:
            continue
        w, h = SIZES[kind(bpmn_type)]
        _, ly, _, lh = lanes[lane]
        cx = FIRST_COLUMN_X + column * COLUMN_WIDTH + 65
        bounds[node_id] = (cx - w / 2, ly + (lh - h) / 2, w, h)
    for node_id, (host, _) in BOUNDARY.items():  # on the host's bottom edge
        hx, hy, hw, hh = bounds[host]
        w, h = SIZES["event"]
        bounds[node_id] = (hx + hw / 2 - w / 2, hy + hh - h / 2, w, h)
    return bounds


def waypoints(source, target, route, b):
    sx, sy, sw, sh = b[source]
    tx, ty, tw, th = b[target]
    s_mid, t_mid = (sx + sw / 2, sy + sh / 2), (tx + tw / 2, ty + th / 2)
    if route == "auto":
        start, end = (sx + sw, s_mid[1]), (tx, t_mid[1])
        if abs(start[1] - end[1]) < 1:
            return [start, end]
        if t_mid[0] - s_mid[0] < 1:  # straight down or up in the same column
            return [(s_mid[0], sy + sh if ty > sy else sy), (t_mid[0], ty if ty > sy else ty + th)]
        mid_x = (start[0] + end[0]) / 2
        return [start, (mid_x, start[1]), (mid_x, end[1]), end]
    if route == "down":
        return [(s_mid[0], sy + sh), (t_mid[0], ty)]
    if route == "up":
        return [(s_mid[0], sy), (t_mid[0], ty + th)]
    if route == "gateway_down":  # leave a gateway downwards, then right into the target
        return [(s_mid[0], sy + sh), (s_mid[0], t_mid[1]), (tx, t_mid[1])]
    if route == "right_up":  # leave right, then up into the target's bottom
        return [(sx + sw, s_mid[1]), (t_mid[0], s_mid[1]), (t_mid[0], ty + th)]
    if route == "back_up":  # from a lower lane back to an earlier node above
        return [(sx, s_mid[1]), (t_mid[0], s_mid[1]), (t_mid[0], ty + th)]
    if route == "back_down":  # from a higher lane back to an earlier node below
        return [(sx, s_mid[1]), (t_mid[0] + 20, s_mid[1]), (t_mid[0] + 20, ty)]
    raise ValueError(route)


# --- XML ------------------------------------------------------------------------

def attr(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def build() -> str:
    b = node_bounds()
    incoming = {n: [] for n in NODES}
    outgoing = {n: [] for n in NODES}
    for flow_id, source, target, _, _ in FLOWS:
        outgoing[source].append(flow_id)
        incoming[target].append(flow_id)

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"',
           '                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
           '                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"',
           '                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"',
           '                  id="Definitions_ToBe"',
           '                  targetNamespace="http://example.com/rheinwerk/ap-spend-leakage">',
           '',
           '  <!-- To-be invoice-to-pay at Rheinwerk HQ (fictional client), Improve task 5.3.',
           '       Generated by scripts/build_to_be_bpmn.py. Lanes are roles or the ERP, never people.',
           '       Text annotations mark each change against the as-is model with its fix number,',
           '       € figure and issue-tree hypothesis. -->',
           '',
           '  <bpmn:collaboration id="Collaboration_ToBe">',
           '    <bpmn:participant id="Participant_Supplier" name="Supplier" />',
           '    <bpmn:participant id="Participant_HQ" name="Rheinwerk HQ: invoice-to-pay (to-be)" processRef="Process_ToBe" />']
    for msg_id, source, target, name in MESSAGES:
        out.append(f'    <bpmn:messageFlow id="{msg_id}" name="{attr(name)}" sourceRef="{source}" targetRef="{target}" />')
    out += ['  </bpmn:collaboration>', '',
            '  <bpmn:process id="Process_ToBe" name="Invoice-to-pay (to-be)" isExecutable="false">',
            '    <bpmn:laneSet id="LaneSet_ToBe">']
    for lane_id, name, _ in LANES:
        out.append(f'      <bpmn:lane id="{lane_id}" name="{attr(name)}">')
        out += [f'        <bpmn:flowNodeRef>{n}</bpmn:flowNodeRef>' for n, v in NODES.items() if v[2] == lane_id]
        out.append('      </bpmn:lane>')
    out.append('    </bpmn:laneSet>')

    for node_id, (bpmn_type, name, _, _) in NODES.items():
        base, _, definition = bpmn_type.partition(":")
        extra = ""
        if node_id in BOUNDARY:
            host, interrupting = BOUNDARY[node_id]
            extra = f' attachedToRef="{host}" cancelActivity="{str(interrupting).lower()}"'
        name_attr = f' name="{attr(name)}"' if name else ""
        out.append(f'    <bpmn:{base} id="{node_id}"{name_attr}{extra}>')
        out += [f'      <bpmn:incoming>{f}</bpmn:incoming>' for f in incoming[node_id]]
        out += [f'      <bpmn:outgoing>{f}</bpmn:outgoing>' for f in outgoing[node_id]]
        if definition == "message":
            out.append(f'      <bpmn:messageEventDefinition id="MED_{node_id}" />')
        elif definition == "timer":
            out.append(f'      <bpmn:timerEventDefinition id="TED_{node_id}" />')
        out.append(f'    </bpmn:{base}>')
    for flow_id, source, target, name, _ in FLOWS:
        name_attr = f' name="{attr(name)}"' if name else ""
        out.append(f'    <bpmn:sequenceFlow id="{flow_id}"{name_attr} sourceRef="{source}" targetRef="{target}" />')
    for note_id, node, text, _, _ in ANNOTATIONS:
        out += [f'    <bpmn:textAnnotation id="{note_id}">', f'      <bpmn:text>{escape(text)}</bpmn:text>',
                '    </bpmn:textAnnotation>',
                f'    <bpmn:association id="Assoc_{note_id}" sourceRef="{node}" targetRef="{note_id}" />']
    out += ['  </bpmn:process>', '',
            '  <bpmndi:BPMNDiagram id="Diagram_ToBe">',
            '    <bpmndi:BPMNPlane id="Plane_ToBe" bpmnElement="Collaboration_ToBe">']

    def shape(element, x, y, w, h, extra=""):
        out.append(f'      <bpmndi:BPMNShape id="{element}_di" bpmnElement="{element}"{extra}>')
        out.append(f'        <dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" />')
        out.append('      </bpmndi:BPMNShape>')

    def edge(element, points):
        out.append(f'      <bpmndi:BPMNEdge id="{element}_di" bpmnElement="{element}">')
        out.extend(f'        <di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in points)
        out.append('      </bpmndi:BPMNEdge>')

    total_height = sum(h for _, _, h in LANES)
    shape("Participant_Supplier", POOL_X, SUPPLIER_Y, pool_width(), SUPPLIER_HEIGHT, ' isHorizontal="true"')
    shape("Participant_HQ", POOL_X, POOL_Y, pool_width(), total_height, ' isHorizontal="true"')
    for lane_id, (x, y, w, h) in lane_bounds().items():
        shape(lane_id, x, y, w, h, ' isHorizontal="true"')
    for node_id, (x, y, w, h) in b.items():
        if kind(NODES[node_id][0]) == "gateway":
            # Label above the gateway: the "No" flows leave from its bottom.
            out.append(f'      <bpmndi:BPMNShape id="{node_id}_di" bpmnElement="{node_id}" isMarkerVisible="true">')
            out.append(f'        <dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" />')
            out.append(f'        <bpmndi:BPMNLabel><dc:Bounds x="{x + w / 2 - 50:.0f}" y="{y - 32:.0f}" '
                       'width="100" height="27" /></bpmndi:BPMNLabel>')
            out.append('      </bpmndi:BPMNShape>')
        else:
            shape(node_id, x, y, w, h)
    note_bounds = {}
    for note_id, node, _, dx, dy in ANNOTATIONS:
        x, y, _, _ = b[node]
        if dy < 0 and node != "End_BudgetActed":  # in the band between the supplier pool and the ERP lane
            note_bounds[note_id] = (x + dx, NOTE_Y, NOTE_WIDTH, NOTE_HEIGHT)
        elif node == "End_BudgetActed":
            note_bounds[note_id] = (x + dx, y + dy, 220, 60)
        else:
            note_bounds[note_id] = (x + dx, y + dy, NOTE_WIDTH + 40, 80)
        shape(note_id, *note_bounds[note_id])
    for flow_id, source, target, _, route in FLOWS:
        edge(flow_id, waypoints(source, target, route, b))
    for note_id, node, _, _, _ in ANNOTATIONS:
        x, y, w, h = b[node]
        nx, ny, nw, nh = note_bounds[note_id]
        start = (x + w / 2, y) if ny < y else (x + 10, y + h)
        if node == "End_BudgetActed":
            start = (x + w, y + h / 2)
        end = (nx + nw / 2, ny + nh) if ny < y else (nx + nw / 2, ny)
        if node == "End_BudgetActed":
            end = (nx, ny + nh / 2)
        edge(f"Assoc_{note_id}", [start, end])
    supplier_bottom = SUPPLIER_Y + SUPPLIER_HEIGHT
    for msg_id, source, target, _ in MESSAGES:
        if source == "Participant_Supplier":
            x, y, w, _ = b[target]
            edge(msg_id, [(x + w / 2, supplier_bottom), (x + w / 2, y)])
        else:
            x, y, w, _ = b[source]
            # Leave the task on the right of centre so the line doesn't cover the incoming flow.
            edge(msg_id, [(x + w / 2 + 50, y), (x + w / 2 + 50, supplier_bottom)])
    out += ['    </bpmndi:BPMNPlane>', '  </bpmndi:BPMNDiagram>', '</bpmn:definitions>', '']
    return "\n".join(out)


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        handle.write(build())
