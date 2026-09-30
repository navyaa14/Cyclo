// CYCLOPS: observed flood extent for Cyclone Fani from Sentinel-1 SAR (Google Earth Engine Code Editor).
// Method: change detection on VH backscatter (after / before ratio), following the widely used
// UN-SPIDER recommended practice. SAR sees through cloud, which optical imagery cannot during a cyclone.
// Output: a flood mask you can export (GeoTIFF / GeoJSON) and load as the "Observed" layer in VERIFY.
// NOTE: dates, threshold and orbit are starting points. Check scene availability and tune the threshold.

var aoi = ee.Geometry.Rectangle([85.45, 19.64, 86.45, 20.34]); // Puri coastal demo box
var beforeStart = '2019-04-10', beforeEnd = '2019-04-30';     // pre-event
var afterStart  = '2019-05-03', afterEnd  = '2019-05-12';     // Fani landfall 3 May 2019
var polarization = 'VH';
var passDirection = 'DESCENDING';                              // try ASCENDING if no scenes
var diffThreshold = 1.25;                                      // ratio threshold (tune)

var s1 = ee.ImageCollection('COPERNICUS/S1_GRD')
  .filter(ee.Filter.eq('instrumentMode', 'IW'))
  .filter(ee.Filter.listContains('transmitterReceiverPolarisation', polarization))
  .filter(ee.Filter.eq('orbitProperties_pass', passDirection))
  .filter(ee.Filter.eq('resolution_meters', 10))
  .filterBounds(aoi)
  .select(polarization);

var before = s1.filterDate(beforeStart, beforeEnd).mosaic().clip(aoi);
var after  = s1.filterDate(afterStart, afterEnd).mosaic().clip(aoi);
print('Scenes before:', s1.filterDate(beforeStart, beforeEnd).size());
print('Scenes after:', s1.filterDate(afterStart, afterEnd).size());

// Speckle reduction
var smoothing = 50;
var beforeF = before.focal_mean(smoothing, 'circle', 'meters');
var afterF  = after.focal_mean(smoothing, 'circle', 'meters');

// Change detection: water lowers backscatter, so after/before ratio drops
var ratio = afterF.divide(beforeF);
var flooded = ratio.lt(1 / diffThreshold).rename('water').selfMask();

// Remove permanent / seasonal water (JRC Global Surface Water)
var gsw = ee.Image('JRC/GSW1_4/GlobalSurfaceWater');
var permanent = gsw.select('seasonality').gte(10);
flooded = flooded.where(permanent, 0).selfMask();

// Remove steep terrain (SAR shadow / layover)
var dem = ee.Image('WWF/HydroSHEDS/03VFDEM');
var slope = ee.Algorithms.Terrain(dem).select('slope');
flooded = flooded.updateMask(slope.lt(5));

// Remove isolated pixels
var connections = flooded.connectedPixelCount(25);
flooded = flooded.updateMask(connections.gte(8));

Map.centerObject(aoi, 10);
Map.addLayer(beforeF, {min: -25, max: 0}, 'Before (VH)', false);
Map.addLayer(afterF, {min: -25, max: 0}, 'After (VH)', false);
Map.addLayer(flooded, {palette: ['C1272D']}, 'Observed flood extent');

// Flooded area (km2)
var area = flooded.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: aoi, scale: 10, bestEffort: true
});
print('Flooded area (km2):', ee.Number(area.get('water')).divide(1e6));

// Export at the CYCLOPS grid resolution (0.025 deg ~ 2.7 km) as fraction flooded per cell
var fraction = flooded.unmask(0).reduceResolution({reducer: ee.Reducer.mean(), maxPixels: 65536})
  .reproject({crs: 'EPSG:4326', scale: 2750});
Export.image.toDrive({
  image: fraction, description: 'cyclops_fani_observed_flood_fraction',
  region: aoi, scale: 2750, crs: 'EPSG:4326', maxPixels: 1e10
});
