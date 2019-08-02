# =============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================


import math
from functools import lru_cache

from eos.const import FittingHardpoint
from eos.saveddata.fit import Fit
from gui.builtinGraphs.fitDamageStats.helper import getTgtRadius
from service.const import GraphDpsDroneMode
from service.settings import GraphSettings


def getApplicationPerKey(fit, tgt, atkSpeed, atkAngle, distance, tgtSpeed, tgtAngle, tgtSigRadius):
    applicationMap = {}
    for mod in fit.modules:
        if not mod.isDealingDamage():
            continue
        if mod.hardpoint == FittingHardpoint.TURRET:
            applicationMap[mod] = getTurretMult(
                mod=mod,
                fit=fit,
                tgt=tgt,
                atkSpeed=atkSpeed,
                atkAngle=atkAngle,
                distance=distance,
                tgtSpeed=tgtSpeed,
                tgtAngle=tgtAngle,
                tgtSigRadius=tgtSigRadius)
        elif mod.hardpoint == FittingHardpoint.MISSILE:
            applicationMap[mod] = getLauncherMult(
                mod=mod,
                fit=fit,
                distance=distance,
                tgtSpeed=tgtSpeed,
                tgtSigRadius=tgtSigRadius)
        elif mod.item.group.name in ('Smart Bomb', 'Structure Area Denial Module'):
            applicationMap[mod] = getSmartbombMult(
                mod=mod,
                distance=distance)
        elif mod.item.group.name == 'Missile Launcher Bomb':
            applicationMap[mod] = getBombMult(
                mod=mod,
                fit=fit,
                tgt=tgt,
                distance=distance,
                tgtSigRadius=tgtSigRadius)
        elif mod.item.group.name == 'Structure Guided Bomb Launcher':
            applicationMap[mod] = getGuidedBombMult(
                mod=mod,
                fit=fit,
                distance=distance,
                tgtSigRadius=tgtSigRadius)
        elif mod.item.group.name in ('Super Weapon', 'Structure Doomsday Weapon'):
            applicationMap[mod] = getDoomsdayMult(
                mod=mod,
                tgt=tgt,
                distance=distance,
                tgtSigRadius=tgtSigRadius)
    for drone in fit.drones:
        if not drone.isDealingDamage():
            continue
        applicationMap[drone] = getDroneMult(
            drone=drone,
            fit=fit,
            tgt=tgt,
            atkSpeed=atkSpeed,
            atkAngle=atkAngle,
            distance=distance,
            tgtSpeed=tgtSpeed,
            tgtAngle=tgtAngle,
            tgtSigRadius=tgtSigRadius)
    for fighter in fit.fighters:
        if not fighter.isDealingDamage():
            continue
        for ability in fighter.abilities:
            if not ability.dealsDamage or not ability.active:
                continue
            applicationMap[(fighter, ability.effectID)] = getFighterAbilityMult(
                fighter=fighter,
                ability=ability,
                fit=fit,
                distance=distance,
                tgtSpeed=tgtSpeed,
                tgtSigRadius=tgtSigRadius)
    return applicationMap


# Item application multiplier calculation
def getTurretMult(mod, fit, tgt, atkSpeed, atkAngle, distance, tgtSpeed, tgtAngle, tgtSigRadius):
    cth = _calcTurretChanceToHit(
        atkSpeed=atkSpeed,
        atkAngle=atkAngle,
        atkRadius=fit.ship.getModifiedItemAttr('radius'),
        atkOptimalRange=mod.maxRange,
        atkFalloffRange=mod.falloff,
        atkTracking=mod.getModifiedItemAttr('trackingSpeed'),
        atkOptimalSigRadius=mod.getModifiedItemAttr('optimalSigRadius'),
        distance=distance,
        tgtSpeed=tgtSpeed,
        tgtAngle=tgtAngle,
        tgtRadius=getTgtRadius(tgt),
        tgtSigRadius=tgtSigRadius)
    mult = _calcTurretMult(cth)
    return mult


def getLauncherMult(mod, fit, distance, tgtSpeed, tgtSigRadius):
    modRange = mod.maxRange
    if modRange is None:
        return 0
    if distance is not None and distance + fit.ship.getModifiedItemAttr('radius') > modRange:
        return 0
    mult = _calcMissileFactor(
        atkEr=mod.getModifiedChargeAttr('aoeCloudSize'),
        atkEv=mod.getModifiedChargeAttr('aoeVelocity'),
        atkDrf=mod.getModifiedChargeAttr('aoeDamageReductionFactor'),
        tgtSpeed=tgtSpeed,
        tgtSigRadius=tgtSigRadius)
    return mult


def getSmartbombMult(mod, distance):
    modRange = mod.maxRange
    if modRange is None:
        return 0
    if distance is not None and distance > modRange:
        return 0
    return 1


def getDoomsdayMult(mod, tgt, distance, tgtSigRadius):
    modRange = mod.maxRange
    # Single-target DDs have no range limit
    if distance is not None and modRange and distance > modRange:
        return 0
    # Single-target titan DDs are vs capitals only
    if {'superWeaponAmarr', 'superWeaponCaldari', 'superWeaponGallente', 'superWeaponMinmatar'}.intersection(mod.item.effects):
        # Disallow only against subcap fits, allow against cap fits and tgt profiles
        if isinstance(tgt, Fit) and not tgt.ship.item.requiresSkill('Capital Ships'):
            return 0
    damageSig = mod.getModifiedItemAttr('doomsdayDamageRadius') or mod.getModifiedItemAttr('signatureRadius')
    if not damageSig:
        return 1
    return min(1, tgtSigRadius / damageSig)


def getBombMult(mod, fit, tgt, distance, tgtSigRadius):
    modRange = mod.maxRange
    if modRange is None:
        return 0
    blastRadius = mod.getModifiedChargeAttr('explosionRange')
    atkRadius = fit.ship.getModifiedItemAttr('radius')
    tgtRadius = getTgtRadius(tgt)
    # Bomb starts in the center of the ship
    # Also here we assume that it affects target as long as blast
    # touches its surface, not center - I did not check this
    if distance is not None and distance < max(0, modRange - atkRadius - tgtRadius - blastRadius):
        return 0
    if distance is not None and distance > max(0, modRange - atkRadius + tgtRadius + blastRadius):
        return 0
    return _calcBombFactor(
        atkEr=mod.getModifiedChargeAttr('aoeCloudSize'),
        tgtSigRadius=tgtSigRadius)


def getGuidedBombMult(mod, fit, distance, tgtSigRadius):
    modRange = mod.maxRange
    if modRange is None:
        return 0
    if distance is not None and distance > modRange - fit.ship.getModifiedItemAttr('radius'):
        return 0
    eR = mod.getModifiedChargeAttr('aoeCloudSize')
    if eR == 0:
        return 1
    else:
        return min(1, tgtSigRadius / eR)


def getDroneMult(drone, fit, tgt, atkSpeed, atkAngle, distance, tgtSpeed, tgtAngle, tgtSigRadius):
    if distance is not None and distance > fit.extraAttributes['droneControlRange']:
        return 0
    droneSpeed = drone.getModifiedItemAttr('maxVelocity')
    # Hard to simulate drone behavior, so assume chance to hit is 1 for mobile drones
    # which catch up with target
    droneOpt = GraphSettings.getInstance().get('mobileDroneMode')
    if (
        droneSpeed > 1 and (
            (droneOpt == GraphDpsDroneMode.auto and droneSpeed >= tgtSpeed) or
            droneOpt == GraphDpsDroneMode.followTarget)
    ):
        cth = 1
    # Otherwise put the drone into center of the ship, move it at its max speed or ship's speed
    # (whichever is lower) towards direction of attacking ship and see how well it projects
    else:
        droneRadius = drone.getModifiedItemAttr('radius')
        if distance is None:
            cthDistance = None
        else:
            # As distance is ship surface to ship surface, we adjust it according
            # to attacker fit's radiuses to have drone surface to ship surface distance
            cthDistance = distance + fit.ship.getModifiedItemAttr('radius') - droneRadius
        cth = _calcTurretChanceToHit(
            atkSpeed=min(atkSpeed, droneSpeed),
            atkAngle=atkAngle,
            atkRadius=droneRadius,
            atkOptimalRange=drone.maxRange,
            atkFalloffRange=drone.falloff,
            atkTracking=drone.getModifiedItemAttr('trackingSpeed'),
            atkOptimalSigRadius=drone.getModifiedItemAttr('optimalSigRadius'),
            distance=cthDistance,
            tgtSpeed=tgtSpeed,
            tgtAngle=tgtAngle,
            tgtRadius=getTgtRadius(tgt),
            tgtSigRadius=tgtSigRadius)
    mult = _calcTurretMult(cth)
    return mult


def getFighterAbilityMult(fighter, ability, fit, distance, tgtSpeed, tgtSigRadius):
    fighterSpeed = fighter.getModifiedItemAttr('maxVelocity')
    attrPrefix = ability.attrPrefix
    # It's bomb attack
    if attrPrefix == 'fighterAbilityLaunchBomb':
        # Just assume we can land bomb anywhere
        return _calcBombFactor(
            atkEr=fighter.getModifiedChargeAttr('aoeCloudSize'),
            tgtSigRadius=tgtSigRadius)
    droneOpt = GraphSettings.getInstance().get('mobileDroneMode')
    # It's regular missile-based attack
    if (droneOpt == GraphDpsDroneMode.auto and fighterSpeed >= tgtSpeed) or droneOpt == GraphDpsDroneMode.followTarget:
        rangeFactor = 1
    # Same as with drones, if fighters are slower - put them to center of
    # the ship and see how they apply
    else:
        if distance is None:
            rangeFactorDistance = None
        else:
            rangeFactorDistance = distance + fit.ship.getModifiedItemAttr('radius') - fighter.getModifiedItemAttr('radius')
        rangeFactor = _calcRangeFactor(
            atkOptimalRange=fighter.getModifiedItemAttr('{}RangeOptimal'.format(attrPrefix)) or fighter.getModifiedItemAttr('{}Range'.format(attrPrefix)),
            atkFalloffRange=fighter.getModifiedItemAttr('{}RangeFalloff'.format(attrPrefix)),
            distance=rangeFactorDistance)
    drf = fighter.getModifiedItemAttr('{}ReductionFactor'.format(attrPrefix), None)
    if drf is None:
        drf = fighter.getModifiedItemAttr('{}DamageReductionFactor'.format(attrPrefix))
    drs = fighter.getModifiedItemAttr('{}ReductionSensitivity'.format(attrPrefix), None)
    if drs is None:
        drs = fighter.getModifiedItemAttr('{}DamageReductionSensitivity'.format(attrPrefix))
    missileFactor = _calcMissileFactor(
        atkEr=fighter.getModifiedItemAttr('{}ExplosionRadius'.format(attrPrefix)),
        atkEv=fighter.getModifiedItemAttr('{}ExplosionVelocity'.format(attrPrefix)),
        atkDrf=_calcAggregatedDrf(reductionFactor=drf, reductionSensitivity=drs),
        tgtSpeed=tgtSpeed,
        tgtSigRadius=tgtSigRadius)
    mult = rangeFactor * missileFactor
    return mult


# Turret-specific math
@lru_cache(maxsize=50)
def _calcTurretMult(chanceToHit):
    """Calculate damage multiplier for turret-based weapons."""
    # https://wiki.eveuniversity.org/Turret_mechanics#Damage
    wreckingChance = min(chanceToHit, 0.01)
    wreckingPart = wreckingChance * 3
    normalChance = chanceToHit - wreckingChance
    if normalChance > 0:
        avgDamageMult = (0.01 + chanceToHit) / 2 + 0.49
        normalPart = normalChance * avgDamageMult
    else:
        normalPart = 0
    totalMult = normalPart + wreckingPart
    return totalMult


@lru_cache(maxsize=1000)
def _calcTurretChanceToHit(
    atkSpeed, atkAngle, atkRadius, atkOptimalRange, atkFalloffRange, atkTracking, atkOptimalSigRadius,
    distance, tgtSpeed, tgtAngle, tgtRadius, tgtSigRadius
):
    """Calculate chance to hit for turret-based weapons."""
    # https://wiki.eveuniversity.org/Turret_mechanics#Hit_Math
    angularSpeed = _calcAngularSpeed(atkSpeed, atkAngle, atkRadius, distance, tgtSpeed, tgtAngle, tgtRadius)
    rangeFactor = _calcRangeFactor(atkOptimalRange, atkFalloffRange, distance)
    trackingFactor = _calcTrackingFactor(atkTracking, atkOptimalSigRadius, angularSpeed, tgtSigRadius)
    cth = rangeFactor * trackingFactor
    return cth


def _calcAngularSpeed(atkSpeed, atkAngle, atkRadius, distance, tgtSpeed, tgtAngle, tgtRadius):
    """Calculate angular speed based on mobility parameters of two ships."""
    if distance is None:
        return 0
    atkAngle = atkAngle * math.pi / 180
    tgtAngle = tgtAngle * math.pi / 180
    ctcDistance = atkRadius + distance + tgtRadius
    # Target is to the right of the attacker, so transversal is projection onto Y axis
    transSpeed = abs(atkSpeed * math.sin(atkAngle) - tgtSpeed * math.sin(tgtAngle))
    if ctcDistance == 0:
        return 0 if transSpeed == 0 else math.inf
    else:
        return transSpeed / ctcDistance


def _calcTrackingFactor(atkTracking, atkOptimalSigRadius, angularSpeed, tgtSigRadius):
    """Calculate tracking chance to hit component."""
    return 0.5 ** (((angularSpeed * atkOptimalSigRadius) / (atkTracking * tgtSigRadius)) ** 2)


# Missile-specific math
@lru_cache(maxsize=200)
def _calcMissileFactor(atkEr, atkEv, atkDrf, tgtSpeed, tgtSigRadius):
    """Missile application."""
    factors = [1]
    # "Slow" part
    if atkEr > 0:
        factors.append(tgtSigRadius / atkEr)
    # "Fast" part
    if tgtSpeed > 0:
        factors.append(((atkEv * tgtSigRadius) / (atkEr * tgtSpeed)) ** atkDrf)
    totalMult = min(factors)
    return totalMult


def _calcAggregatedDrf(reductionFactor, reductionSensitivity):
    """
    Sometimes DRF is specified as 2 separate numbers,
    here we combine them into generic form.
    """
    return math.log(reductionFactor) / math.log(reductionSensitivity)


# Generic math
def _calcRangeFactor(atkOptimalRange, atkFalloffRange, distance):
    """Range strength/chance factor, applicable to guns, ewar, RRs, etc."""
    if distance is None:
        return 1
    if atkFalloffRange > 0:
        return 0.5 ** ((max(0, distance - atkOptimalRange) / atkFalloffRange) ** 2)
    elif distance <= atkOptimalRange:
        return 1
    else:
        return 0


def _calcBombFactor(atkEr, tgtSigRadius):
    if atkEr == 0:
        return 1
    else:
        return min(1, tgtSigRadius / atkEr)