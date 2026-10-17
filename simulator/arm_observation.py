"""Interpret measured surfaces using public kinematics, never target identities."""
import math
from .camera import sub,add,scale,dot,norm,transpose,matvec
from .common import digest

GRASP_GUIDE=dict(
    coordinates='Right-handed world coordinates in meters: x lateral, y UP, z longitudinal. World z is not camera range. Rotation is XYZ Euler degrees.',
    pose_reference='move_arm pose is the CENTER of the jaw contact region, not the wrist joint, finger tips, or a measured plant surface.',
    fingers=dict(length_m=.16,center_relative_y_m=0,tip_relative_y_m=-.08,closing_axis='tool local x',open_gap_m=.12),
    grasp=dict(tool_center_height_m=[.09,.22],suggested_center_height_m=.15,maximum_tilt_degrees=25,horizontal_tolerance_m=.055,minimum_close_force_N=8,extraction_force_N=26),
    conversion='Identify the lower central stem in RGB. Use consistent non-ground, non-robot returns to estimate its horizontal x,z; leaf edges are not the stem. For an upright stem grasp, command [estimated_x,0.15,estimated_z,0,0,0]. Do not copy surface y into tool-center height: a 0.08 m ground projection is too low and a 0.30 m leaf return is too high.',
    approach='Approach with open jaws, observe and scan at the new viewpoint, then assess alignment. Closing requires both fingers and the central stem to be inspectable. If occluded, change viewpoint before assessing.',
    contact='A visual assessment is only a claim. After closing, inspect a fresh image and require holding=true and positive measured load, then confirm_contact before lifting. For extraction lift vertically at least 0.18 m before carrying to the bin.',
    recovery='After a miss or slip: reopen, inspect feedback and actual tool height, change the grasp pose or viewpoint, rescan, reassess. Repeating the same pose or images is not recovery.')

def segment_distance(p,a,b):
    delta=sub(b,a);length=dot(delta,delta)
    t=max(0,min(1,dot(sub(p,a),delta)/length)) if length else 0
    return norm(sub(p,add(a,scale(delta,t))))

def box_contains(p,center,half):
    return all(abs(a-b)<=h+.006 for a,b,h in zip(p,center,half))

def robot_surface(p,pose,opening,base_position):
    points=pose['points'];r=pose['rotation']
    for i,(a,b) in enumerate(zip(points,points[1:])):
        if i==2:b=add(b,scale([r[0][1],r[1][1],r[2][1]],.13))
        if segment_distance(p,a,b)<=(.09 if i<2 else .04):return True
    if any(norm(sub(p,center))<=.116 for center in points[:3]):return True
    local=matvec(transpose(r),sub(p,pose['position']))
    if box_contains(local,[0,.1,0],[.09,.04,.05]):return True
    for sign in (-1,1):
        if box_contains(local,[sign*(opening/2+.009),0,0],[.009,.08,.0225]):return True
    rover=sub(p,[base_position[0],0,base_position[1]])
    return (box_contains(rover,[0,.48,0],[.625,.2,.85]) or
            box_contains(rover,[0,.85,.45],[.525,.06,.4]) or
            box_contains(rover,[0,1.06,.45],[.275,.2,.325]) or
            any(box_contains(rover,[x,.38,z],[.11,.32,.32]) for x in (-.7,.7) for z in (-.58,.58)))

def interpret_scan(points,camera,pose,opening,base_position):
    classes=[];ranges=[]
    for row in points:
        if row is None:classes.append('no_return');ranges.append(None);continue
        p=row[2:];ranges.append(round(norm(sub(p,camera['position'])),5))
        classes.append('robot_geometry' if robot_surface(p,pose,opening,base_position) else 'ground_plane' if p[1]<=.025 else 'unclassified_surface')
    return dict(columns=['u','v','world_x','world_y','world_z'],units=['normalized_image','normalized_image','meters','meters','meters'],
                image_origin='top-left; u increases right, v increases down',world_up_axis='y',
                return_semantics='First visible surface along each ordered camera ray. Returns can hit foliage, stem, protected plants, arm or ground. They are NOT target coordinates; null means no return.',
                filtering='Conservative masks from known robot link/jaw/chassis geometry and the known ground plane; unclassified does not mean weed or stem. Raw returns remain available.',
                surface_classes=classes,range_m=ranges,candidate_indices=[i for i,c in enumerate(classes) if c=='unclassified_surface'])


def progress_state(world,action):
    """Count unchanged/previously visited views separately from physical milestones."""
    pose=world.tool_pose();position=pose['position'];angles=pose['euler']
    state=getattr(world,'control_progress',None) or dict(views=[],milestones=[],stagnant_actions=0,recovery_required=False,incidents=0)
    novel=not any(norm(sub(position,v[:3]))<.02 and max(abs(a-b) for a,b in zip(angles,v[3:]))<3 for v in state['views'])
    milestones=[name for name,value in [('contact',world.holding and world.load>0),('extracted',world.extracted),('collected',world.deposited),('returned',world.return_verified)] if value]
    previous_physical=state.get('previous_physical',{})
    physical=dict(contact=world.holding and world.load>0,extracted=world.extracted,collected=world.deposited,returned=world.return_verified)
    new_milestone=any(value and not previous_physical.get(name,False) for name,value in physical.items())
    state['previous_physical']=physical
    signature=digest(dict(action=action,pose=[round(p,3) for p in position+angles],opening=round(world.opening,3),force=round(world.force,1),physical=physical))
    repeated=signature in state.get('steps',[])
    state['steps']=(state.get('steps',[])+[signature])[-40:]
    if novel:state['views']=(state['views']+[position[:]+angles[:]])[-16:]
    state['milestones']=list(dict.fromkeys(state['milestones']+milestones))
    state['stagnant_actions']=0 if novel or new_milestone else state['stagnant_actions']+int(repeated)
    previous=state['recovery_required'];state['recovery_required']=state['stagnant_actions']>=4
    if state['recovery_required'] and not previous:
        state['incidents']+=1;world.event('progress_stalled','T1',last_action=action,stagnant_actions=state['stagnant_actions'])
    state['last_action']=action
    state['guidance']='Change viewpoint or grasp pose by at least 2 cm or 3 degrees; reopen first after a miss. Repeated capture/scan/assessment at the same pose cannot recover. Stop if no safe alternative.' if state['recovery_required'] else 'Progress counts new viewpoints and actual contact/recovered contact/extraction/collection/return, not image count or revision increments.'
    world.control_progress=state
    return state
