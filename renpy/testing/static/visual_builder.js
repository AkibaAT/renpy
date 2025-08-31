let selectedObject = null;
let isDragging = false;
let dragOffset = { x: 0, y: 0 };
let sceneObjects = [];
let gridEnabled = true;

// Initialize the visual builder
document.addEventListener('DOMContentLoaded', function() {
    loadAssets();
    loadScene();
    setupEventListeners();
});

function setupEventListeners() {
    const canvas = document.getElementById('sceneCanvas');
    
    // Mouse tracking for coordinates
    canvas.addEventListener('mousemove', function(e) {
        const rect = canvas.getBoundingClientRect();
        const x = Math.round(e.clientX - rect.left);
        const y = Math.round(e.clientY - rect.top);
        document.getElementById('coordinates').textContent = `X: ${x}, Y: ${y}`;
    });
    
    // Canvas click to deselect
    canvas.addEventListener('click', function(e) {
        if (e.target === canvas) {
            selectObject(null);
        }
    });
}

function loadAssets() {
    console.log('Loading assets...');
    fetch('/api/debug/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({'action': 'get_assets', 'type': 'all'})
    })
    .then(response => response.json())
    .then(data => {
        console.log('Assets response:', data);
        if (data.success && data.result) {
            console.log('Assets data:', data.result.assets);
            renderAssets(data.result.assets);
        } else {
            console.error('Assets request failed:', data);
        }
    })
    .catch(error => console.error('Error loading assets:', error));
}

function renderAssets(assets) {
    console.log('Rendering assets:', assets);
    
    // Render character assets
    const characterContainer = document.getElementById('characterAssets');
    characterContainer.innerHTML = '';
    
    if (assets && assets.images) {
        console.log('Found images:', assets.images);
        assets.images.forEach(asset => {
            if (asset.category === 'Characters') {
                const assetElement = createAssetElement(asset);
                characterContainer.appendChild(assetElement);
            }
        });
    } else {
        console.log('No assets.images found');
        characterContainer.innerHTML = '<p>No character assets found</p>';
    }
    
    // Render background assets
    const backgroundContainer = document.getElementById('backgroundAssets');
    backgroundContainer.innerHTML = '';
    
    if (assets.backgrounds) {
        console.log('Found backgrounds:', assets.backgrounds);
        assets.backgrounds.forEach(asset => {
            const assetElement = createAssetElement(asset);
            backgroundContainer.appendChild(assetElement);
        });
    } else {
        console.log('No assets.backgrounds found');
        backgroundContainer.innerHTML = '<p>No background assets found</p>';
    }
    
    // Also render any images that are backgrounds
    if (assets.images) {
        assets.images.forEach(asset => {
            if (asset.category === 'Backgrounds') {
                const assetElement = createAssetElement(asset);
                backgroundContainer.appendChild(assetElement);
            }
        });
    }
    
    // Render props
    const propContainer = document.getElementById('propAssets');
    if (propContainer) {
        propContainer.innerHTML = '';
        if (assets.images) {
            assets.images.forEach(asset => {
                if (asset.category === 'Props') {
                    const assetElement = createAssetElement(asset);
                    propContainer.appendChild(assetElement);
                }
            });
        }
        if (propContainer.innerHTML === '') {
            propContainer.innerHTML = '<p>No prop assets found</p>';
        }
    }
}

function createAssetElement(asset) {
    const div = document.createElement('div');
    div.className = 'asset-item';
    div.textContent = asset.name;
    div.draggable = true;
    div.dataset.tag = asset.tag;
    div.dataset.type = asset.type;
    
    // Drag start
    div.addEventListener('dragstart', function(e) {
        e.dataTransfer.setData('text/plain', JSON.stringify({
            tag: asset.tag,
            name: asset.name,
            type: asset.type,
            attributes: asset.attributes || []
        }));
    });
    
    return div;
}

function loadScene() {
    console.log('Loading scene...');
    fetch('/api/debug/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({'action': 'get_scene_render_data'})
    })
    .then(response => response.json())
    .then(data => {
        console.log('Scene response:', data);
        if (data.success && data.result) {
            console.log('Scene render data:', data.result.render_data);
            renderScene(data.result.render_data);
        } else {
            console.error('Scene request failed:', data);
        }
    })
    .catch(error => console.error('Error loading scene:', error));
}

function renderScene(renderData) {
    console.log('Rendering scene:', renderData);
    
    const canvas = document.getElementById('sceneCanvas');
    canvas.innerHTML = '';
    sceneObjects = [];
    
    if (!renderData) {
        console.error('No render data provided');
        canvas.innerHTML = '<p style="color: red;">No scene data available</p>';
        return;
    }
    
    // Set canvas size to match game resolution
    if (renderData.scene_size) {
        const scaleX = canvas.offsetWidth / renderData.scene_size.width;
        const scaleY = canvas.offsetHeight / renderData.scene_size.height;
        const scale = Math.min(scaleX, scaleY, 1.0); // Don't scale up
        
        canvas.style.transform = `scale(${scale})`;
        canvas.style.transformOrigin = 'top left';
        canvas.style.width = renderData.scene_size.width + 'px';
        canvas.style.height = renderData.scene_size.height + 'px';
        
        console.log(`Game resolution: ${renderData.scene_size.width}x${renderData.scene_size.height}, scale: ${scale}`);
    }
    
    // Collect all objects for the scene list
    const allObjects = [];
    
    // Render backgrounds first (lowest z-index)
    if (renderData.backgrounds) {
        console.log('Found backgrounds:', renderData.backgrounds);
        renderData.backgrounds.forEach(bg => {
            allObjects.push(bg);
            if (bg.visible !== false) {
                const element = createSceneObject(bg);
                canvas.appendChild(element);
            }
            sceneObjects.push(bg);
        });
    }
    
    // Render objects (higher z-index)
    if (renderData.objects) {
        console.log('Found objects:', renderData.objects);
        renderData.objects.forEach(obj => {
            allObjects.push(obj);
            if (obj.visible !== false) {
                const element = createSceneObject(obj);
                canvas.appendChild(element);
            }
            sceneObjects.push(obj);
        });
    }
    
    // Render screens (highest z-index)
    if (renderData.screens) {
        console.log('Found screens:', renderData.screens);
        renderData.screens.forEach(screen => {
            allObjects.push(screen);
            if (screen.visible !== false) {
                const element = createSceneObject(screen);
                element.style.opacity = '0.3'; // Make screens semi-transparent
                canvas.appendChild(element);
            }
            sceneObjects.push(screen);
        });
    }
    
    // Update scene objects list
    updateSceneObjectsList(allObjects);
    
    // Setup drop zone
    setupDropZone(canvas);
}

function createSceneObject(obj) {
    const div = document.createElement('div');
    div.className = 'scene-object';
    div.id = obj.id;

    // Create image element for actual displayable image
    const img = document.createElement('img');
    // Use the image_url from scene data if available, otherwise fallback to old format
    const imageUrl = obj.image_url || `/api/debug/image/${obj.tag}/${obj.layer || 'master'}`;
    console.log(`Loading image for ${obj.tag}: ${imageUrl}`);
    img.src = imageUrl;
    img.style.width = '100%';
    img.style.height = '100%';
    img.style.objectFit = 'contain';
    img.style.pointerEvents = 'none'; // Allow clicks to pass through to parent

    // Add fallback text overlay for identification
    const label = document.createElement('div');
    label.style.position = 'absolute';
    label.style.bottom = '0';
    label.style.left = '0';
    label.style.right = '0';
    label.style.background = 'rgba(0,0,0,0.7)';
    label.style.color = 'white';
    label.style.padding = '2px 5px';
    label.style.fontSize = '12px';
    label.style.textAlign = 'center';
    label.style.pointerEvents = 'none';

    // Set label content based on object type
    if (obj.type === 'background') {
        label.textContent = `BG: ${obj.tag}`;
    } else if (obj.type === 'character') {
        label.textContent = obj.tag;
    } else if (obj.type === 'screen') {
        label.textContent = `Screen: ${obj.name}`;
    } else {
        label.textContent = obj.name || obj.tag;
    }

    // Handle image load errors - fallback to colored box
    img.onerror = function() {
        console.warn(`Failed to load image for ${obj.tag}, using fallback`);
        div.removeChild(img);
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.justifyContent = 'center';
        div.style.fontSize = '14px';
        div.style.fontWeight = 'bold';
        div.style.color = 'white';
        div.style.textShadow = '1px 1px 2px rgba(0,0,0,0.7)';
        div.appendChild(document.createTextNode(label.textContent));
    };

    div.appendChild(img);
    div.appendChild(label);
    
    // Position and size
    div.style.position = 'absolute';
    div.style.left = obj.position.x + 'px';
    div.style.top = obj.position.y + 'px';
    div.style.width = obj.size.width + 'px';
    div.style.height = obj.size.height + 'px';
    div.style.backgroundColor = obj.color;
    div.style.zIndex = obj.z_index || 100;
    
    // Visual styling based on type
    if (obj.type === 'background') {
        div.style.border = '3px solid #2980b9';
        div.style.opacity = '0.7';
    } else if (obj.type === 'character') {
        div.style.border = '3px solid #e74c3c';
        div.style.opacity = '0.9';
    } else if (obj.type === 'screen') {
        div.style.border = '2px dashed #95a5a6';
        div.style.opacity = '0.3';
        div.style.backgroundColor = 'transparent';
    } else {
        div.style.border = '2px solid #3498db';
    }
    
    div.dataset.tag = obj.tag;
    div.dataset.type = obj.type;
    
    // Make draggable
    if (obj.draggable) {
        setupObjectDragging(div, obj);
    }
    
    // Click to select
    div.addEventListener('click', function(e) {
        e.stopPropagation();
        selectObject(obj);
    });
    
    return div;
}

function setupObjectDragging(element, obj) {
    element.addEventListener('mousedown', function(e) {
        if (e.button === 0) { // Left mouse button
            isDragging = true;
            element.classList.add('dragging');

            const rect = element.getBoundingClientRect();
            const canvasRect = document.getElementById('sceneCanvas').getBoundingClientRect();

            dragOffset.x = e.clientX - rect.left;
            dragOffset.y = e.clientY - rect.top;

            selectObject(obj);

            e.preventDefault();
        }
    });

    document.addEventListener('mousemove', function(e) {
        if (isDragging && element.classList.contains('dragging')) {
            const canvasRect = document.getElementById('sceneCanvas').getBoundingClientRect();
            let x = e.clientX - canvasRect.left - dragOffset.x;
            let y = e.clientY - canvasRect.top - dragOffset.y;

            // Snap to grid if enabled
            if (gridEnabled) {
                x = Math.round(x / 20) * 20;
                y = Math.round(y / 20) * 20;
            }

            // Keep within bounds
            x = Math.max(0, Math.min(x, canvasRect.width - element.offsetWidth));
            y = Math.max(0, Math.min(y, canvasRect.height - element.offsetHeight));

            element.style.left = x + 'px';
            element.style.top = y + 'px';

            // Update object position
            obj.position.x = x;
            obj.position.y = y;

            updateObjectProperties();
        }
    });

    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            element.classList.remove('dragging');

            // Send position update to server
            updateObjectPosition(obj);
        }
    });
}

function setupDropZone(canvas) {
    canvas.addEventListener('dragover', function(e) {
        e.preventDefault();
    });

    canvas.addEventListener('drop', function(e) {
        e.preventDefault();

        const data = JSON.parse(e.dataTransfer.getData('text/plain'));
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // Add object to scene
        addObjectToScene(data, x, y);
    });
}

function addObjectToScene(assetData, x, y) {
    // Send show command to server
    fetch('/api/debug/scene/show', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            tag: assetData.tag,
            attributes: assetData.attributes,
            transforms: [],
            layer: 'master'
        })
    })
    .then(response => response.json())
    .then(result => {
        if (result.action === 'show') {
            // Update position
            updateObjectPosition({
                tag: assetData.tag,
                position: { x: x, y: y }
            });

            // Reload scene
            setTimeout(loadScene, 100);
        }
    })
    .catch(error => console.error('Error adding object:', error));
}

function updateObjectPosition(obj) {
    fetch('/api/debug/set-position', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            tag: obj.tag,
            x: obj.position.x,
            y: obj.position.y
        })
    })
    .catch(error => console.error('Error updating position:', error));
}

function selectObject(obj) {
    // Remove previous selection
    document.querySelectorAll('.scene-object').forEach(el => {
        el.style.border = el.dataset.type === 'background' ? '3px solid #2980b9' :
                         el.dataset.type === 'character' ? '3px solid #e74c3c' : '2px solid #3498db';
    });

    selectedObject = obj;

    if (obj) {
        // Highlight selected object
        const element = document.getElementById(obj.id);
        if (element) {
            element.style.border = '3px solid #f39c12';
        }

        // Update properties panel
        updateObjectProperties();
    } else {
        // Clear properties panel
        document.getElementById('objectProperties').innerHTML = '<p>Select an object to edit properties</p>';
    }
}

function updateObjectProperties() {
    if (!selectedObject) return;

    const panel = document.getElementById('objectProperties');
    panel.innerHTML = `
        <div class="property-group">
            <label>Tag:</label>
            <input type="text" value="${selectedObject.tag}" readonly>
        </div>

        <h4 style="color: #1abc9c; margin: 15px 0 10px 0;">Position</h4>
        <div class="property-group">
            <label>X Position:</label>
            <input type="number" value="${selectedObject.position.x}" onchange="updatePosition('x', this.value)">
        </div>
        <div class="property-group">
            <label>Y Position:</label>
            <input type="number" value="${selectedObject.position.y}" onchange="updatePosition('y', this.value)">
        </div>

        <h4 style="color: #1abc9c; margin: 15px 0 10px 0;">Size</h4>
        <div class="property-group">
            <label>Width:</label>
            <input type="number" value="${selectedObject.size.width}" onchange="updateSize('width', this.value)">
        </div>
        <div class="property-group">
            <label>Height:</label>
            <input type="number" value="${selectedObject.size.height}" onchange="updateSize('height', this.value)">
        </div>

        <h4 style="color: #1abc9c; margin: 15px 0 10px 0;">Actions</h4>
        <div class="property-group">
            <button class="btn btn-success" onclick="duplicateObject()" style="margin: 2px;">📋 Duplicate</button>
            <button class="btn btn-danger" onclick="removeObject()" style="margin: 2px;">🗑️ Remove</button>
        </div>
    `;
}

function updatePosition(axis, value) {
    if (!selectedObject) return;

    selectedObject.position[axis] = parseInt(value);
    const element = document.getElementById(selectedObject.id);
    if (element) {
        element.style[axis === 'x' ? 'left' : 'top'] = value + 'px';
    }

    updateObjectPosition(selectedObject);
}

function updateSize(dimension, value) {
    if (!selectedObject) return;

    selectedObject.size[dimension] = parseInt(value);
    const element = document.getElementById(selectedObject.id);
    if (element) {
        element.style[dimension] = value + 'px';
    }
}

function removeObject() {
    if (!selectedObject) return;

    fetch('/api/debug/scene/hide', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            tag: selectedObject.tag,
            layer: selectedObject.layer || 'master'
        })
    })
    .then(() => {
        selectObject(null);
        loadScene();
    })
    .catch(error => console.error('Error removing object:', error));
}

function duplicateObject() {
    if (!selectedObject) return;

    const newTag = selectedObject.tag + '_copy';
    const offsetX = selectedObject.position.x + 50;
    const offsetY = selectedObject.position.y + 50;

    // Show duplicate object
    fetch('/api/debug/scene/show', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            tag: newTag,
            attributes: selectedObject.attributes || [],
            transforms: selectedObject.transforms || [],
            layer: selectedObject.layer || 'master'
        })
    })
    .then(() => {
        // Set position for duplicate
        return fetch('/api/debug/set-position', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                tag: newTag,
                x: offsetX,
                y: offsetY
            })
        });
    })
    .then(() => {
        // Reload scene to show duplicate
        setTimeout(loadScene, 100);
    })
    .catch(error => console.error('Error duplicating object:', error));
}

function toggleGrid() {
    gridEnabled = !gridEnabled;
    const canvas = document.getElementById('sceneCanvas');
    if (gridEnabled) {
        canvas.style.backgroundImage = 'linear-gradient(45deg, #f0f0f0 25%, transparent 25%), linear-gradient(-45deg, #f0f0f0 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #f0f0f0 75%), linear-gradient(-45deg, transparent 75%, #f0f0f0 75%)';
    } else {
        canvas.style.backgroundImage = 'none';
    }
}

function saveScene() {
    // Show apply changes dialog from the main scene objects view
    window.open('/webview/scene-objects', '_blank');
}

function clearScene() {
    if (confirm('Clear all objects from the scene?')) {
        fetch('/api/debug/scene/scene', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ tag: null })
        })
        .then(() => loadScene())
        .catch(error => console.error('Error clearing scene:', error));
    }
}

function addObject() {
    // Simple add object dialog
    const tag = prompt('Enter object tag:');
    if (tag) {
        addObjectToScene({ tag: tag, name: tag, attributes: [] }, 960, 500);
    }
}

function updateSceneObjectsList(objects) {
    const container = document.getElementById('sceneObjectsList');
    container.innerHTML = '';

    if (!objects || objects.length === 0) {
        container.innerHTML = '<p>No scene objects found</p>';
        return;
    }

    objects.forEach(obj => {
        const item = document.createElement('div');
        item.className = 'scene-object-item' + (obj.visible === false ? ' hidden' : '');
        item.innerHTML = `
            <span class="scene-object-name" onclick="selectObjectById('${obj.id}')" title="Size: ${obj.size.width}x${obj.size.height}">
                ${obj.type.toUpperCase()}: ${obj.tag || obj.name}
            </span>
            <button class="scene-object-toggle" onclick="toggleObjectVisibility('${obj.id}')" title="Toggle visibility">
                ${obj.visible === false ? '👁️' : '🙈'}
            </button>
        `;
        container.appendChild(item);
    });
}

function selectObjectById(objectId) {
    const obj = sceneObjects.find(o => o.id === objectId);
    if (obj) {
        selectObject(obj);
    }
}

function toggleObjectVisibility(objectId) {
    const obj = sceneObjects.find(o => o.id === objectId);
    if (obj) {
        obj.visible = obj.visible === false ? true : false;

        // Update the visual element
        const element = document.getElementById(objectId);
        if (element) {
            if (obj.visible === false) {
                element.style.display = 'none';
            } else {
                element.style.display = 'block';
            }
        }

        // Update the list item
        const listItems = document.querySelectorAll('.scene-object-item');
        listItems.forEach(item => {
            const nameSpan = item.querySelector('.scene-object-name');
            if (nameSpan && nameSpan.getAttribute('onclick').includes(objectId)) {
                item.className = 'scene-object-item' + (obj.visible === false ? ' hidden' : '');
                const toggleBtn = item.querySelector('.scene-object-toggle');
                toggleBtn.textContent = obj.visible === false ? '👁️' : '🙈';
            }
        });

        console.log(`Toggled visibility for ${obj.tag}: ${obj.visible}`);
    }
}
