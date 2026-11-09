<script setup lang="ts">
// 轻量地图组件：Leaflet + OSM 瓦片（免 key）。
// 三点标记：商家(绿)/目的地(红)/骑手(蓝)，骑手位置变化平滑更新。
import { onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps<{
  merchant?: { lat: number; lng: number; name?: string } | null
  dest?: { lat: number; lng: number; text?: string } | null
  rider?: { lat: number | null; lng: number | null; name?: string } | null
}>()

const el = ref<HTMLElement | null>(null)
let map: L.Map | null = null
let markers: Record<string, L.Marker> = {}

function dotIcon(color: string, label: string) {
  return L.divIcon({
    className: '',
    html: `<div style="width:26px;height:26px;border-radius:50%;background:${color};border:3px solid #fff;
      box-shadow:0 1px 6px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;
      color:#fff;font-size:11px;font-weight:700">${label}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}

const ICONS = {
  merchant: () => dotIcon('#0aa858', '店'),
  dest: () => dotIcon('#e8552f', '家'),
  rider: () => dotIcon('#2f6fe8', '骑'),
}

function setMarker(kind: 'merchant' | 'dest' | 'rider', pos: { lat: number; lng: number }, popup: string) {
  if (!map) return
  if (markers[kind]) {
    markers[kind].setLatLng([pos.lat, pos.lng])
  } else {
    markers[kind] = L.marker([pos.lat, pos.lng], { icon: ICONS[kind]() }).addTo(map!).bindPopup(popup)
  }
}

function fitAll() {
  const pts: [number, number][] = Object.values(markers).map((m) => m.getLatLng()) as [number, number][]
  if (pts.length === 1) map?.setView(pts[0], 14)
  else if (pts.length > 1) map?.fitBounds(L.latLngBounds(pts).pad(0.3))
}

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { zoomControl: true, attributionControl: true })
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  }).addTo(map)
  map.setView([30.512, 114.43], 13)
  apply()
})

function apply() {
  if (props.merchant?.lat) setMarker('merchant', props.merchant, props.merchant.name || '取餐点')
  if (props.dest?.lat) setMarker('dest', props.dest, props.dest.text || '目的地')
  if (props.rider?.lat && props.rider?.lng) setMarker('rider', props.rider, props.rider.name || '骑手')
  fitAll()
}

watch(() => [props.merchant, props.dest, props.rider], apply, { deep: true })

onUnmounted(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="el" style="width: 100%; height: 100%"></div>
</template>
