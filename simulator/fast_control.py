"""Measured care automation. This module accepts policy observations, never worlds.

Vision owns specimen identity, image targets and alignment. Every returned action
still crosses the ordinary command, trajectory, contact and verification guards.
"""
import math

PROMPT="""You are the visual decision maker for a simulated orchard robot. Use the named tools and current RGB. Code handles metered care and bounded arm motion; you identify caterpillars and weed root crowns and assess visual alignment. Preserve ladybirds and rounded clover. Pixel candidates are unclassified RGB components. For pests choose a visible caterpillar center; for weeds choose a lower-edge point at the root crown. Use exactly one named function, never Python or code execution. Never select robot fingers or leaf tips. Use the exact current frame_id. If no safe choice exists, stop. Be concise. Physical contact, load and completion are independently checked."""
from .camera import project_pixel


def viewpoint_pose(obs):
    """A novel observation pose from public kinematics, never a plant target."""
    from .arm import ik
    pose=obs['tool_pose']['position'];views=(obs.get('controller_progress') or {}).get('views',[])
    for dx,dy,dz in ((0,0,0),(.08,.06,0),(-.08,.12,0),(0,.18,.08)):
        target=[pose[0]+dx,.46+dy,pose[2]+.12+dz,0,0,0]
        if math.dist(target[:3],pose)<.02 or any(math.dist(target[:3],v[:3])<.02 for v in views):continue
        try:ik(target,obs['base'])
        except ValueError:continue
        return target
    return None


def automatic_action(obs):
    frame=obs.get('frame')
    if not frame:return None
    phase=obs['phase'];allowed=obs['available_actions']
    def action(name,**args):
        return (name,dict(frame_id=frame['id'],**args)) if name in allowed else None
    if phase=='inspection':return action('inspect_tree')
    if phase=='final':return action('verify')
    if phase in ('irrigation','fertilizer'):
        for name in ('read_moisture','read_application','next_stage'):
            if name in allowed:return action(name)
        if not obs.get('aimed'):
            x,_,z=obs['task_tree']['position']
            u,v=project_pixel(frame['camera'],[x,.08,z+.35])
            return action('aim_nozzle',u=u,v=v)
        return action('water_tree' if phase=='irrigation' else 'fertilize_tree')
    if phase=='pests':
        # Ask the ordinary independent verifier once per geometry revision.
        # Rejection leaves vision responsible for identifying the next pest.
        probed=any(e.get('payload',{}).get('receipt',{}).get('action')=='next_stage' and
                   e['payload']['receipt'].get('revision')==frame['revision'] for e in obs.get('history',[]))
        return None if probed else action('next_stage')
    if phase!='extraction':return None
    grip=obs['gripper'];pose=obs['tool_pose']['position'];protocol=obs['protocol']
    if grip['deposited']:return action('verify')
    if grip['holding']:
        if grip['load']<=0:return None
        if not protocol['contact_acknowledged']:
            return action('confirm_contact',evidence='Fresh frame retained; measured holding=true and positive load confirm contact.')
        if not grip['extracted']:
            return action('move_arm',pose=[pose[0],pose[1]+.22,pose[2],0,0,0])
        bx,_,bz=obs['bin']
        if math.hypot(pose[0]-bx,pose[2]-bz)<.02 and abs(pose[1]-.8)<.02:return action('open_gripper')
        return action('move_arm',pose=[bx,.8,bz,0,0,0])
    if grip['must_reopen'] or grip['opening']<.06:return action('open_gripper')
    progress=obs.get('controller_progress') or {}
    if progress.get('recovery_required'):
        target=viewpoint_pose(obs)
        return action('move_arm',pose=target) if target else action('stop')
    recovery=obs.get('current_grasp_step',{}).get('wide_view_pose')
    if recovery:
        if math.dist(pose,recovery[:3])>.02:return action('move_arm',pose=recovery)
        return None
    if not protocol['nonempty_scan']:return None
    alignment=protocol.get('alignment')
    if alignment and alignment['aligned'] and alignment['revision']==frame['revision']:
        return action('set_gripper',opening=0,force=30)
    projection=obs.get('crown_projection')
    if pose[1]>.55 and projection and projection.get('revision')!=frame['revision']:
        scan=obs.get('scan')
        if scan and scan['frame_id']==frame['id'] and scan['revision']==frame['revision']:
            u0,v0,u1,v1=scan['bounds']
            return action('project_ground',u=(u0+u1)/2,v=(v0+v1)/2)
        return None
    if not projection:
        scan=obs.get('scan')
        if scan and scan['frame_id']==frame['id'] and scan['revision']==frame['revision']:
            u0,v0,u1,v1=scan['bounds']
            return action('project_ground',u=(u0+u1)/2,v=(v0+v1)/2)
        return None
    target=projection['world'];x,z=target['x'],target['z']
    if pose[1]>.55:return action('move_arm',pose=[x,.4,z+.2,0,0,0])
    if pose[1]>.22:
        # Require vision to refine the root crown from the closer image.
        if projection['revision']!=frame['revision']:return None
        return action('move_arm',pose=[x,.13,z,0,0,0])
    if projection['revision']==frame['revision'] and math.hypot(pose[0]-x,pose[2]-z)>.005:
        return action('move_arm',pose=[x,.13,z,0,0,0])
    return None


def vision_observation(obs):
    """Small stage-specific payload, including only already-public measurements."""
    keys=('mission_id','kind','status','phase','trial','worker','frame','camera','feedback','sensors','resources','recovery','recovery_attempts','recovery_history',
          'budgets','controller_progress','current_grasp_step','care_progress','task_tree','tool_pose','base','bin','gripper','protocol','crown_projection','scan','scan_stale')
    result={k:obs[k] for k in keys if k in obs};result['controller']='ultra_fast'
    allowed=obs['available_actions'];phase=obs['phase'];grip=obs.get('gripper',{})
    if phase=='pests':wanted=['remove_pest','stop']
    elif not obs['protocol']['nonempty_scan'] or obs.get('current_grasp_step',{}).get('wide_view_pose') or obs['tool_pose']['position'][1]>.55 and obs.get('scan_stale'):wanted=['scan_lidar','stop']
    elif obs['tool_pose']['position'][1]>.22 or not obs.get('crown_projection'):wanted=['project_ground','stop']
    else:wanted=['assess_alignment','project_ground','stop']
    if phase=='extraction' and not grip.get('holding') and 'move_arm' in allowed:
        view=viewpoint_pose(obs)
        if view:result['viewpoint_pose']=view;wanted.append('move_arm')
        anchor=(obs.get('crown_projection') or {}).get('world')
        if anchor and obs['tool_pose']['position'][1]<=.55:result['refinement_region']=dict(center=anchor,radius_m=.18)
    result['available_actions']=[a for a in wanted if a in allowed]
    result['instructions']='''Choose one action using current RGB. Routine care and bounded arm motion run automatically.
PESTS: choose the candidate ID centered on a visible elongated brown/purple caterpillar (or image u,v if no candidates are offered). Preserve round red ladybirds. Code requests independent stage clearance; you only select a visible pest or stop.
WEED: choose the root crown where upright grass, serrated rosette or thistle meets soil. Rounded three-leaf clover must be preserved. scan_lidar: u,v at that crown, span=.16. project_ground: refine the visible ROOT/SOIL junction, not a leaf. Both use normalized image coordinates and current frame_id. Never invent world coordinates.
RECOVERY: Use recovery_history to avoid repeating failed targets and visual claims. If the root is obscured or no local candidate matches, use move_arm to the supplied viewpoint_pose for a new image. Refinement stays within the supplied region around the previously selected crown; never jump to neighboring clover. If no safe action is available, stop requests a new recovery approach; the unfinished task remains active.
ALIGNMENT: assess_alignment only if both inner finger faces and the weed stem are visible and the stem lies between them; depth_consistent must reflect measured geometry. Otherwise project_ground at the correct crown or stop. Evidence is not physical contact; measured holding/load and preservation checks remain mandatory.
Keep reason brief. Include the current frame_id in every call.'''
    # A bounded spatial sample retains the measured surfaces without repeating a
    # whole LiDAR grid and full control history in every vision request.
    if result.get('scan'):
        result['scan']=dict(result['scan']);points=result['scan'].get('returns',[])
        if len(points)>32:result['scan']['returns']=points[::math.ceil(len(points)/32)]
    return result


def pixel_candidates(pixels,obs):
    """Unclassified connected RGB regions; no scene IDs or target coordinates.

    A model must still identify a weed in RGB. Close refinements remain within 18 cm of the previously selected public projection. Components may include clover or
    robot surfaces. The lower-edge point is only a visual hypothesis; all usual
    LiDAR, alignment and independent contact checks still apply.
    """
    from .png import components
    if obs['phase']=='pests':
        return [dict(id='p'+str(i),color='purple',**c) for i,c in enumerate(components(pixels,'pest',include_bounds=True)[:8])]
    from .camera import project_ground,add,matvec
    from .arm import ik
    # Mask only public gripper geometry. Its shaded finger faces can also be
    # green components; they are never a plant candidate. No scene inventory.
    pose=obs['tool_pose'];opening=obs['gripper']['opening'];masks=[]
    boxes=[([sign*(opening/2+.009),0,0],[.009,.065,.02]) for sign in (-1,1)]
    boxes.append(([0,.09,0],[.085,.0375,.0425]))
    for center,half in boxes:
        corners=[]
        try:
            for sx in (-1,1):
                for sy in (-1,1):
                    for sz in (-1,1):
                        local=[center[i]+sign*half[i] for i,sign in enumerate((sx,sy,sz))]
                        corners.append(project_pixel(obs['frame']['camera'],add(pose['position'],matvec(pose['rotation'],local))))
            masks.append((min(p[0] for p in corners)-.006,min(p[1] for p in corners)-.006,max(p[0] for p in corners)+.006,max(p[1] for p in corners)+.006))
        except ValueError:pass
    candidates=[]
    anchor=(obs.get('crown_projection') or {}).get('world') if pose['position'][1]<=.55 else None
    regions=[dict(c,color='yellow-green') for c in components(pixels,'yellow_green',include_bounds=True)]+[dict(c,color='green') for c in components(pixels,'vegetation',include_bounds=True)]
    for component in regions:
        if component['area']<4:continue
        if any(math.hypot(c['u']-component['u'],c['v']-component['v'])<.006 for c in candidates):continue
        if any(a<=component['u']<=c and b<=component['v']<=d for a,b,c,d in masks):continue
        try:
            p=project_ground(obs['frame']['camera'],component['u'],component['v'])
            ik([p[0],.13,p[2],0,0,0],obs['base'])
        except ValueError:continue
        if anchor:
            distance=math.hypot(p[0]-anchor['x'],p[2]-anchor['z'])
            if distance>=.18:continue
            component=dict(component,refinement_distance_m=round(distance,4))
        candidates.append(component)
    if anchor:candidates.sort(key=lambda c:c['refinement_distance_m'])
    return [dict(id='c'+str(i),**c) for i,c in enumerate(candidates[:8])]
