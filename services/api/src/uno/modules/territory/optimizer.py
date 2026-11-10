"""Optimización de una jornada en minutos locales, con matriz vial y pausas reales."""

from __future__ import annotations

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def optimize(
    candidates: list[dict],
    matrix: dict,
    *,
    start: int,
    end: int,
    lunch_start: int = 720,
    lunch_end: int = 780,
    max_contacts: int = 12,
    max_medical: int = 10,
    max_pharmacies: int = 5,
    return_to_origin: bool = False,
    end_index: int = 0,
    time_limit: int = 4,
) -> dict:
    if lunch_start <= start < lunch_end:
        start = lunch_end
    if start >= end:
        return {
            "stops": [],
            "dropped": [x["key"] for x in candidates],
            "feasible": False,
            "reason": "La jornada ya terminó",
        }
    if not candidates:
        return {"stops": [], "dropped": [], "feasible": True, "finish": start, "travel_minutes": 0}
    n = len(candidates) + 1 + int(end_index != 0)
    manager = pywrapcp.RoutingIndexManager(n, 1, [0], [end_index])
    routing = pywrapcp.RoutingModel(manager)
    durations = [0] + [x["service"] for x in candidates] + ([0] if end_index else [])

    def transit(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        travel = 0 if b == 0 and not return_to_origin else matrix["minutes"][a][b]
        return int(travel + durations[a])

    callback = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(callback)
    routing.AddDimension(callback, 1440, 1440, False, "Time")
    times = routing.GetDimensionOrDie("Time")
    times.CumulVar(routing.Start(0)).SetRange(start, start)
    times.CumulVar(routing.End(0)).SetRange(start, end)
    # Prefer shorter working days as well as shorter drives; waiting has a real cost.
    times.SetSpanCostCoefficientForAllVehicles(2)
    # Marketing consumes time and travel, but does not claim a medical/PDV contact.
    contacts = (
        [0] + [int(c.get("kind") != "marketing") for c in candidates] + ([0] if end_index else [])
    )
    contacts_callback = routing.RegisterUnaryTransitCallback(
        lambda idx: contacts[manager.IndexToNode(idx)]
    )
    routing.AddDimensionWithVehicleCapacity(contacts_callback, 0, [max_contacts], True, "Stops")
    for kind, maximum in [("doctor", max_medical), ("pharmacy", max_pharmacies)]:
        counts = [0] + [int(c.get("kind") == kind) for c in candidates] + ([0] if end_index else [])
        count_callback = routing.RegisterUnaryTransitCallback(
            lambda idx, counts=counts: counts[manager.IndexToNode(idx)]
        )
        routing.AddDimensionWithVehicleCapacity(count_callback, 0, [maximum], True, kind)
    for i, item in enumerate(candidates, 1):
        idx = manager.NodeToIndex(i)
        lo = max(start, item["opens"])
        hi = min(end - item["service"], item["closes"] - item["service"])
        windows = item.get("reception_windows") or [[item["opens"], item["closes"]]]
        allowed = []
        for opening, closing in windows:
            left, right = max(lo, opening), min(hi, closing - item["service"])
            for a, b in [
                (left, min(right, lunch_start - item["service"])),
                (max(left, lunch_end), right),
            ]:
                if a <= b:
                    allowed.append((a, b))
        allowed.sort()
        if not allowed:
            if item.get("mandatory"):
                return {
                    "stops": [],
                    "dropped": [x["key"] for x in candidates],
                    "feasible": False,
                    "reason": "Una cita fija no cabe en su ventana",
                }
            routing.ActiveVar(idx).SetValue(0)
        else:
            # Union of reception windows, never bridge a closed interval between shifts.
            times.CumulVar(idx).SetRange(allowed[0][0], max(b for _, b in allowed))
            right = allowed[0][1]
            for a, b in allowed[1:]:
                if a > right + 1:
                    times.CumulVar(idx).RemoveInterval(right + 1, a - 1)
                right = max(right, b)
        if not item.get("mandatory"):
            routing.AddDisjunction([idx], 100000 + int(item.get("priority", 1)) * 1000)
        routing.AddVariableMinimizedByFinalizer(times.CumulVar(idx))
    if start < lunch_start and end > lunch_end:
        lunch = routing.solver().FixedDurationIntervalVar(
            lunch_start, lunch_start, lunch_end - lunch_start, False, "Almuerzo"
        )
        times.SetBreakIntervalsOfVehicle(
            [lunch], 0, [durations[manager.IndexToNode(i)] for i in range(routing.Size())]
        )
    routing.AddVariableMinimizedByFinalizer(times.CumulVar(routing.End(0)))
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = time_limit
    solution = routing.SolveWithParameters(params)
    if not solution:
        return {
            "stops": [],
            "dropped": [x["key"] for x in candidates],
            "feasible": False,
            "reason": "No se encontró una ruta compatible con las citas, pausa y capacidad",
        }
    stops = []
    travel_total = 0
    previous = 0
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        node = manager.IndexToNode(idx)
        if node:
            item = dict(candidates[node - 1])
            arrival = solution.Value(times.CumulVar(idx))
            travel = int(matrix["minutes"][previous][node])
            item.update(
                arrival_minute=arrival,
                departure_minute=arrival + item["service"],
                travel_minutes=travel,
                distance_m=int(matrix["meters"][previous][node]),
            )
            stops.append(item)
            travel_total += travel
            previous = node
        idx = solution.Value(routing.NextVar(idx))
    if return_to_origin:
        travel_total += matrix["minutes"][previous][end_index]
    selected = {x["key"] for x in stops}
    return {
        "stops": stops,
        "dropped": [x["key"] for x in candidates if x["key"] not in selected],
        "feasible": True,
        "finish": solution.Value(times.CumulVar(idx)),
        "travel_minutes": travel_total,
    }
