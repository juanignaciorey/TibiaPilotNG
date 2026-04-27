from src.repositories.radar.core import getClosestWaypointIndexFromCoordinate, getCoordinate
from src.utils.memory import memory_reader
from src.utils.pointer_scanner import pointer_scanner
from ...typings import Context


def setRadarMiddleware(context: Context) -> Context:
    game = (context.get('memory_profile') or {}).get('game')
    if game and memory_reader.attached:
        x = pointer_scanner.read_pointer(game, 'player_x')
        y = pointer_scanner.read_pointer(game, 'player_y')
        z = pointer_scanner.read_pointer(game, 'player_z')
        if x is not None and y is not None and z is not None:
            context['ng_radar']['previousCoordinate'] = context['ng_radar']['coordinate']
            context['ng_radar']['coordinate'] = (x, y, z)
            return context
    # Fallback: image-based radar extraction
    context['ng_radar']['coordinate'] = getCoordinate(
        context['ng_screenshot'], previousCoordinate=context['ng_radar']['previousCoordinate'])
    return context


def setWaypointIndexMiddleware(context: Context) -> Context:
    if context['ng_cave']['waypoints']['currentIndex'] is None:
        context['ng_cave']['waypoints']['currentIndex'] = getClosestWaypointIndexFromCoordinate(
            context['ng_radar']['coordinate'], context['ng_cave']['waypoints']['items'])
    return context
