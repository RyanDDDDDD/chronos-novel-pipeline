import { Handle, Position } from '@xyflow/react'

const centerHandleStyle = { top: '50%' }

/** Shared by all stage nodes. Default left/right center handles keep the main
 *  horizontal chain; named side handles let fan-out edges exit the correct port. */
export default function StageHandles() {
  return (
    <>
      <Handle type="target" position={Position.Left} style={centerHandleStyle} />
      <Handle id="target-right" type="target" position={Position.Right} style={centerHandleStyle} />
      <Handle type="source" position={Position.Right} style={centerHandleStyle} />
      <Handle id="source-left" type="source" position={Position.Left} style={centerHandleStyle} />
    </>
  )
}
