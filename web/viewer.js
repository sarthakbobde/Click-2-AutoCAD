// three.js OBJ viewer: orbit controls, auto-fit, wireframe toggle. Renders on demand.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';

export class ModelViewer {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf3f4f7);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(2, 3, 2.5);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-2.5, 1.5, -2);
    this.scene.add(fill);

    this.material = new THREE.MeshStandardMaterial({ color: 0xcfd5df, roughness: 0.55, metalness: 0.05 });
    this.edgeMaterial = new THREE.LineBasicMaterial({ color: 0x1f2937, transparent: true, opacity: 0.35 });

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener('change', () => this.requestRender());

    this.model = null;
    this.grid = null;
    this.size = new THREE.Vector3(1, 1, 1);
    this.renderPending = false;

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
  }

  requestRender() {
    if (this.renderPending) return;
    this.renderPending = true;
    requestAnimationFrame(() => {
      this.renderPending = false;
      this.controls.update(); // keeps firing 'change' while damping settles
      this.renderer.render(this.scene, this.camera);
    });
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  async load(url) {
    const obj = await new OBJLoader().loadAsync(url);
    this.clear();

    const parts = [];
    let triangles = 0;
    obj.traverse((child) => {
      if (!child.isMesh) return;
      child.material = this.material;
      child.add(new THREE.LineSegments(new THREE.EdgesGeometry(child.geometry, 30), this.edgeMaterial));
      parts.push(child.name || 'part');
      const position = child.geometry.attributes.position;
      triangles += (child.geometry.index ? child.geometry.index.count : position.count) / 3;
    });

    // Sit the model on the grid, centred. Blender's OBJ export is Y-up, like three.js.
    const box = new THREE.Box3().setFromObject(obj);
    box.getSize(this.size);
    const center = box.getCenter(new THREE.Vector3());
    obj.position.set(-center.x, -box.min.y, -center.z);
    this.scene.add(obj);
    this.model = obj;

    const extent = Math.max(this.size.x, this.size.y, this.size.z) || 1;
    this.grid = new THREE.GridHelper(extent * 4, 20, 0xb8bec9, 0xdde1e7);
    this.scene.add(this.grid);

    this.resetView();
    return { size: this.size.clone(), triangles: Math.round(triangles), parts };
  }

  resetView() {
    const radius = this.size.length() / 2 || 1;
    const distance = (radius / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2))) * 1.1;
    const target = new THREE.Vector3(0, this.size.y / 2, 0);
    this.camera.position.copy(target).add(new THREE.Vector3(1, 0.7, 1.2).normalize().multiplyScalar(distance));
    this.camera.near = distance / 100;
    this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(target);
    this.controls.update();
    this.requestRender();
  }

  setWireframe(on) {
    this.material.wireframe = on;
    this.edgeMaterial.visible = !on;
    this.requestRender();
  }

  clear() {
    if (this.model) {
      this.scene.remove(this.model);
      this.model.traverse((child) => child.geometry?.dispose());
    }
    if (this.grid) {
      this.scene.remove(this.grid);
      this.grid.geometry.dispose();
      this.grid.material.dispose();
    }
    this.model = this.grid = null;
  }

  dispose() {
    this.resizeObserver.disconnect();
    this.clear();
    this.controls.dispose();
    this.material.dispose();
    this.edgeMaterial.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
